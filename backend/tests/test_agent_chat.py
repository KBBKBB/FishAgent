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
