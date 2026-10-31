"""FastAPI router exposing POST /api/agent/chat."""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from fishagent.agent import llm
from fishagent.agent.graph import AGENT_GRAPH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

MAX_HISTORY = 10
GRAPH_ERROR_REPLY = (
    "助手暂时有点忙，请稍后再试。你也可以先查看上方鱼情评分与附近钓位。"
)


class ChatLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    name: str | None = Field(default=None, max_length=120)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    location: ChatLocation
    session_id: str | None = Field(default=None, max_length=64)
    history: list[ChatMessage] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("message 不能为空")
        return text


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error"]


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    mode: Literal["llm", "fallback"]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    fish_activity: dict[str, Any] | None = None
    spots: dict[str, Any] | None = None
    ai_disclosure: str = llm.AI_DISCLOSURE


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    session_id = (payload.session_id or "").strip() or uuid4().hex
    state: dict[str, Any] = {
        "message": payload.message,
        "location": payload.location.model_dump(),
        "session_id": session_id,
        "history": [item.model_dump() for item in payload.history[-MAX_HISTORY:]],
        # Set by the pilot middleware once it has verified the caller. The tools
        # call back into this same app, so they need to present this token or
        # they arrive as an anonymous request and fail with 401.
        "auth_token": getattr(request.state, "pilot_token", None),
    }

    try:
        result = await AGENT_GRAPH.ainvoke(state)
    except Exception:
        logger.exception("agent graph failed")
        return ChatResponse(
            reply=GRAPH_ERROR_REPLY,
            session_id=session_id,
            mode="fallback",
        )

    return ChatResponse(
        reply=result.get("reply") or GRAPH_ERROR_REPLY,
        session_id=session_id,
        mode=result.get("mode") or "fallback",
        tool_calls=[ToolCall(**item) for item in result.get("tool_calls") or []],
        fish_activity=result.get("fish_activity"),
        spots=result.get("spots"),
    )
