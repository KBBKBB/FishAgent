"""LangGraph state machine: intent routing -> tool calls -> answer composition."""

from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from fishagent.agent import llm, tools

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    message: str
    location: dict[str, Any]
    session_id: str
    history: list[dict[str, str]]
    # The caller's pilot token, when the gate is on. The tools re-enter the app
    # through the ASGI app and are therefore subject to the same middleware as
    # any other request; without this they arrive unauthenticated and every
    # tool call fails with 401.
    auth_token: str | None
    intents: list[str]
    species: str | None
    tool_calls: list[dict[str, Any]]
    fish_activity: dict[str, Any] | None
    spots: dict[str, Any] | None
    reply: str
    mode: Literal["llm", "fallback"]


async def route_intent(state: AgentState) -> dict[str, Any]:
    message = state.get("message") or ""
    intents = llm.classify_intents(message)
    species = llm.normalize_species(message)

    client = llm.get_llm_client()
    if not intents and client.enabled:
        classified = await client.classify(message, state.get("history"))
        if classified:
            llm_intents, llm_species = classified
            intents = llm_intents
            species = species or llm_species

    return {"intents": intents, "species": species}


def _next_after_route(state: AgentState) -> Literal["call_tools", "compose_answer"]:
    return "call_tools" if state.get("intents") else "compose_answer"


async def call_tools(state: AgentState) -> dict[str, Any]:
    location = state.get("location") or {}
    lat = float(location.get("lat"))
    lon = float(location.get("lon"))
    location_name = location.get("name") or None
    species = state.get("species")
    intents = state.get("intents") or []

    tool_calls: list[dict[str, Any]] = []
    fish_activity: dict[str, Any] | None = None
    spots: dict[str, Any] | None = None

    # Only the four activity species have a scoring model. Passing anything else
    # is a 422, which would turn a perfectly good bait question about 白条 into
    # an error: ask for the general activity instead and let the bait table
    # supply the species-specific part.
    activity_species = species if species in llm.ALLOWED_SPECIES else None
    auth_token = state.get("auth_token")

    if "fish" in intents or "time" in intents:
        args: dict[str, Any] = {"lat": lat, "lon": lon}
        if activity_species:
            args["species"] = activity_species
        try:
            fish_activity = await tools.get_fish_activity(
                lat,
                lon,
                species=activity_species,
                location_name=location_name,
                auth_token=auth_token,
            )
            tool_calls.append({"name": "get_fish_activity", "args": args, "status": "ok"})
        except Exception:
            logger.warning("get_fish_activity tool failed", exc_info=True)
            tool_calls.append({"name": "get_fish_activity", "args": args, "status": "error"})

    if "spots" in intents:
        args = {"lat": lat, "lon": lon}
        if species:
            args["species"] = species
        try:
            spots = await tools.recommend_spots(
                lat, lon, species=species, auth_token=auth_token
            )
            tool_calls.append({"name": "recommend_spots", "args": args, "status": "ok"})
        except Exception:
            logger.warning("recommend_spots tool failed", exc_info=True)
            tool_calls.append({"name": "recommend_spots", "args": args, "status": "error"})

    return {
        "tool_calls": tool_calls,
        "fish_activity": fish_activity,
        "spots": spots,
    }


async def compose_answer(state: AgentState) -> dict[str, Any]:
    intents = state.get("intents") or []
    fish_activity = state.get("fish_activity")
    spots = state.get("spots")
    location = state.get("location") or {}

    reply: str | None = None
    mode: Literal["llm", "fallback"] = "fallback"

    tool_calls = state.get("tool_calls") or []
    all_tools_failed = bool(tool_calls) and all(
        call.get("status") == "error" for call in tool_calls
    )

    client = llm.get_llm_client()
    if intents and client.enabled and not all_tools_failed:
        reply = await client.compose(
            message=state.get("message") or "",
            location_name=location.get("name"),
            intents=intents,
            species=state.get("species"),
            fish_activity=fish_activity,
            spots=spots,
        )
        if reply and not llm.violates_guardrails(reply):
            mode = "llm"
        else:
            reply = None

    if not reply:
        reply = llm.compose_fallback_reply(
            intents=intents,
            fish_activity=fish_activity,
            spots=spots,
            species=state.get("species"),
        )

    return {"reply": reply, "mode": mode}


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("route_intent", route_intent)
    builder.add_node("call_tools", call_tools)
    builder.add_node("compose_answer", compose_answer)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        _next_after_route,
        {"call_tools": "call_tools", "compose_answer": "compose_answer"},
    )
    builder.add_edge("call_tools", "compose_answer")
    builder.add_edge("compose_answer", END)

    return builder.compile()


AGENT_GRAPH = build_graph()
