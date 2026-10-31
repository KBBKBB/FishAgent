from __future__ import annotations

import re

import pytest
from conftest import HANGZHOU, PROMISE_PATTERNS, assert_unified_error

TIME_RE = re.compile(r"\d{1,2}[:：]\d{2}")


def chat(client, message: str, **overrides):
    payload = {"message": message, "location": {**HANGZHOU, "name": "杭州西湖"}}
    payload.update(overrides)
    return client.post("/api/agent/chat", json=payload)


def chat_ok(client, message: str, **overrides):
    response = chat(client, message, **overrides)
    assert response.status_code == 200, response.text
    return response.json()


def tool_names(payload) -> list[str]:
    return [call["name"] for call in payload["tool_calls"]]


def test_pressure_question_uses_fish_activity_tool(client):
    payload = chat_ok(client, "今天这气压适合钓鱼吗？")
    assert payload["mode"] == "fallback"
    assert "get_fish_activity" in tool_names(payload), payload["tool_calls"]
    assert payload["fish_activity"] is not None
    assert len(payload["fish_activity"]["factors"]) == 7
    assert TIME_RE.search(payload["reply"]), payload["reply"]
    assert any(band in payload["reply"] for band in ("极佳", "良好", "一般", "偏差", "劝退"))


def test_nearby_spots_question_uses_spots_tool(client):
    payload = chat_ok(client, "附近哪里野钓好？")
    assert payload["mode"] == "fallback"
    assert "recommend_spots" in tool_names(payload), payload["tool_calls"]
    assert payload["spots"] is not None
    spots = payload["spots"]["spots"]
    assert spots, payload["spots"]
    assert any(spot["name"] in payload["reply"] for spot in spots), payload["reply"]


def test_best_time_question_returns_window(client):
    payload = chat_ok(client, "明早几点去最好？")
    assert payload["mode"] == "fallback"
    assert "get_fish_activity" in tool_names(payload), payload["tool_calls"]
    assert payload["fish_activity"] is not None
    assert payload["fish_activity"]["best_windows"]
    assert TIME_RE.search(payload["reply"]), payload["reply"]
    assert "看天气" not in payload["reply"]


def test_three_intents_have_ok_tool_calls_and_full_payload(client):
    for message in ("今天这气压适合钓鱼吗？", "附近哪里野钓好？", "明早几点去最好？"):
        payload = chat_ok(client, message)
        assert set(payload) >= {
            "reply",
            "session_id",
            "mode",
            "tool_calls",
            "fish_activity",
            "spots",
            "ai_disclosure",
        }
        assert payload["mode"] in {"llm", "fallback"}
        assert payload["tool_calls"], message
        assert set(tool_names(payload)) <= {"get_fish_activity", "recommend_spots"}, message
        for call in payload["tool_calls"]:
            assert set(call) >= {"name", "args", "status"}
            assert isinstance(call["args"], dict)
            assert call["status"] in {"ok", "error"}
        assert all(call["status"] == "ok" for call in payload["tool_calls"]), message


def test_missing_location_rejected(client):
    response = client.post("/api/agent/chat", json={"message": "今天气压适合钓鱼吗？"})
    assert_unified_error(response, 422, "VALIDATION_ERROR")


def test_invalid_location_rejected(client):
    response = client.post(
        "/api/agent/chat",
        json={"message": "今天气压适合钓鱼吗？", "location": {"lat": 91, "lon": 120.1551}},
    )
    assert_unified_error(response, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("message", ["", "   "])
def test_empty_message_rejected(client, message):
    response = chat(client, message)
    assert_unified_error(response, 422, "VALIDATION_ERROR")


def test_message_length_boundary(client):
    exact_limit = chat(client, "鱼" * 500)
    assert exact_limit.status_code == 200, exact_limit.text

    over_limit = chat(client, "鱼" * 501)
    assert_unified_error(over_limit, 422, "VALIDATION_ERROR")


def test_history_is_truncated_not_rejected(client):
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"历史{index}"}
        for index in range(12)
    ]
    payload = chat_ok(
        client,
        "今天这气压适合钓鱼吗？",
        session_id="qa-session-history",
        history=history,
    )
    assert payload["session_id"] == "qa-session-history"


def test_session_id_is_generated_when_absent(client):
    payload = chat_ok(client, "今天这气压适合钓鱼吗？")
    assert isinstance(payload["session_id"], str) and payload["session_id"]


def test_session_id_is_echoed(client):
    payload = chat_ok(client, "附近哪里野钓好？", session_id="qa-session-echo")
    assert payload["session_id"] == "qa-session-echo"


def test_unknown_intent_returns_guidance(client):
    payload = chat_ok(client, "帮我写首诗")
    assert payload["reply"]
    assert any(word in payload["reply"] for word in ("鱼情", "钓位", "时段", "问题"))


def test_reply_is_two_to_five_sentences(client):
    for message in ("今天这气压适合钓鱼吗？", "附近哪里野钓好？", "明早几点去最好？"):
        payload = chat_ok(client, message)
        sentences = [part for part in re.split(r"[。！？!?]", payload["reply"]) if part.strip()]
        assert 2 <= len(sentences) <= 5, (message, len(sentences), payload["reply"])


def test_ai_disclosure_and_no_promises(client):
    for message in ("今天这气压适合钓鱼吗？", "附近哪里野钓好？", "明早几点去最好？"):
        payload = chat_ok(client, message)
        disclosure = payload["ai_disclosure"]
        assert "AI" in disclosure
        assert "不承诺渔获" in disclosure
        for phrase in PROMISE_PATTERNS:
            assert phrase not in payload["reply"], (phrase, payload["reply"])


# --- bait questions ---------------------------------------------------------
#
# These were reported as broken: "鲫鱼用什么饵料" was answered while
# "白条用什么饵料" returned the generic "I can help with..." guide. The cause was
# that the agent kept its own four-name species list (饵料 questions never
# matched an intent at all, and only 鲫/鲤 had aliases, so 鲫鱼 matched by
# accident). Both halves are covered here: the intent and the species.


@pytest.mark.parametrize(
    "message,species",
    [
        ("鲫鱼用什么饵料", "鲫鱼"),
        ("白条用什么饵料", "白条"),
        ("翘嘴用什么饵料", "翘嘴"),
        ("罗非鱼用什么饵料", "罗非鱼"),
        ("马口怎么钓", "马口"),
        ("胖头鱼用什么饵", "鲢鳙"),
    ],
)
def test_bait_question_answers_for_every_known_species(client, message, species):
    payload = chat_ok(client, message)
    assert payload["mode"] in {"llm", "fallback"}
    reply = payload["reply"]
    # The guide reply is the failure mode this test exists for.
    assert "我可以帮你分析" not in reply, reply
    assert species in reply, reply


def test_bait_question_does_not_depend_on_the_llm(client):
    """Bait comes from a table, so mock mode must still answer.

    Losing the LLM should degrade the wording, not turn an answer into a guide.
    """
    payload = chat_ok(client, "白条用什么饵料")
    assert payload["mode"] == "fallback"
    assert "白条" in payload["reply"]
    assert "饵料" in payload["reply"] or "腥香" in payload["reply"]


def test_bait_question_without_species_still_answers(client):
    payload = chat_ok(client, "用什么饵料好")
    reply = payload["reply"]
    assert "我可以帮你分析" not in reply, reply
    assert "通用" in reply, reply


def test_bait_reply_stays_within_the_sentence_budget(client):
    for message in ("鲫鱼用什么饵料", "白条用什么饵料", "钓鲢鳙用什么饵", "用什么饵料好"):
        payload = chat_ok(client, message)
        sentences = [part for part in re.split(r"[。！？!?]", payload["reply"]) if part.strip()]
        assert 1 <= len(sentences) <= 5, (message, len(sentences), payload["reply"])


def test_bait_and_conditions_share_one_reply(client):
    """Asking both must not drop either half.

    The response carries no intents field, so the evidence is in what got
    called and what came back: the activity tool ran AND the reply names the
    fish.
    """
    payload = chat_ok(client, "今天气压怎么样，白条用什么饵料")
    reply = payload["reply"]
    assert "白条" in reply, reply
    assert "get_fish_activity" in tool_names(payload), payload["tool_calls"]
    assert payload["fish_activity"] is not None

    sentences = [part for part in re.split(r"[。！？!?]", reply) if part.strip()]
    assert len(sentences) <= 5, (len(sentences), reply)


def test_unsupported_activity_species_does_not_break_the_answer(client):
    """白条 has no activity model; asking about conditions must still work.

    Passing it straight through to /api/fish-activity is a 422, which would
    turn a normal question into a failed tool call.
    """
    payload = chat_ok(client, "白条今天适合钓吗")
    calls = payload["tool_calls"]
    assert calls, payload
    activity_call = next(
        call for call in calls if call["name"] == "get_fish_activity"
    )
    assert activity_call["status"] == "ok", calls
    assert "species" not in activity_call["args"], activity_call


def test_bait_composes_with_spots_instead_of_replacing_them(client):
    """Asking for a spot AND bait must return both.

    Bait is answered from a local table, so it is tempting to return early --
    that silently drops the spot recommendation, which is the half the user
    cannot get anywhere else.
    """
    payload = chat_ok(client, "附近哪里钓鲫鱼，用什么饵料")
    reply = payload["reply"]
    # Bait half
    assert "鲫鱼" in reply, reply
    # Spot half: either a spot name or the explicit "none found" wording.
    spots = payload["spots"] or {}
    names = [item["name"] for item in spots.get("spots") or []]
    assert (names and any(name in reply for name in names)) or "钓位" in reply, reply
    assert "recommend_spots" in tool_names(payload), payload["tool_calls"]

    sentences = [part for part in re.split(r"[。！？!?]", reply) if part.strip()]
    assert len(sentences) <= 5, (len(sentences), reply)
