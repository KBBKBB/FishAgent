"""POST /api/agent/transcribe — voice input contract.

The endpoint's job is narrow: accept PCM, bound it, hand it to a provider, and
report what happened truthfully. The interesting cases are all failures, and
each one must say something the user can act on.
"""

from __future__ import annotations

import pytest
from conftest import assert_unified_error

from fishagent.config import get_settings
from fishagent.deps import get_speech_provider
from fishagent.main import app
from fishagent.providers.speech_none import (
    NullSpeechProvider,
    SpeechFailed,
)

SAMPLE_RATE = 16_000
ONE_SECOND = b"\x00\x00" * SAMPLE_RATE


class StubProvider:
    name = "stub"

    def __init__(self, text: str = "鲫鱼用什么饵料", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[int, int]] = []

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        self.calls.append((len(pcm), sample_rate))
        if self.error is not None:
            raise self.error
        return self.text


@pytest.fixture()
def override_provider():
    def install(provider):
        app.dependency_overrides[get_speech_provider] = lambda: provider
        return provider

    yield install
    app.dependency_overrides.pop(get_speech_provider, None)


def post(client, *, audio=ONE_SECOND, sample_rate=SAMPLE_RATE):
    return client.post(
        "/api/agent/transcribe",
        files={"audio": ("speech.pcm", audio, "application/octet-stream")},
        data={"sample_rate": str(sample_rate)},
    )


def test_transcribes_and_returns_text(client, override_provider):
    stub = override_provider(StubProvider("鲫鱼用什么饵料"))
    response = post(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["text"] == "鲫鱼用什么饵料"
    assert payload["provider"] == "stub"
    assert "AI" in payload["ai_disclosure"]
    assert stub.calls == [(len(ONE_SECOND), SAMPLE_RATE)]


def test_text_is_optional_for_the_caller_to_send(client, override_provider):
    """The endpoint must not append the text to the conversation itself.

    Recognition is wrong often enough -- especially the local model on fishing
    terms -- that sending automatically would turn one misheard word into an
    answer the user never asked for. This is a contract of the response shape:
    it is text, not a chat turn.
    """
    override_provider(StubProvider("白条"))
    payload = post(client).json()
    assert set(payload) == {"text", "provider", "ai_disclosure", "generated_at"}


def test_whitespace_only_result_is_treated_as_nothing_heard(client, override_provider):
    override_provider(StubProvider("   "))
    response = post(client)
    assert_unified_error(response, 422, "SPEECH_EMPTY")


def test_empty_result_has_its_own_code(client, override_provider):
    """"Heard nothing" is actionable; "engine broke" is not. Same status, two
    codes, so the UI can say the right thing."""
    override_provider(StubProvider(""))
    empty = post(client)
    assert_unified_error(empty, 422, "SPEECH_EMPTY")

    override_provider(StubProvider(error=SpeechFailed("boom")))
    failed = post(client)
    assert_unified_error(failed, 422, "SPEECH_FAILED")

    # The two messages must differ: sharing one would make the distinction
    # invisible to the user.
    assert empty.json()["detail"]["message"] != failed.json()["detail"]["message"]


def test_engine_unavailable_is_501_not_a_user_problem(client, override_provider):
    override_provider(NullSpeechProvider())
    response = post(client)
    assert_unified_error(response, 501, "SPEECH_UNAVAILABLE")
    message = response.json()["detail"]["message"]
    assert "文字" in message, "must point at the text box as the way forward"


def test_provider_exception_is_not_reported_as_unclear_speech(client, override_provider):
    """A crashing engine must not be told to the user as "speak closer"."""
    override_provider(StubProvider(error=RuntimeError("internal detail")))
    response = post(client)
    assert_unified_error(response, 503, "SPEECH_UNAVAILABLE")
    assert "internal detail" not in response.text


def test_wrong_sample_rate_is_rejected(client, override_provider):
    stub = override_provider(StubProvider())
    response = post(client, sample_rate=44_100)
    assert_unified_error(response, 415, "AUDIO_INVALID")
    assert stub.calls == [], "must not hand a mis-rated buffer to the engine"


def test_empty_upload_is_rejected(client, override_provider):
    override_provider(StubProvider())
    response = post(client, audio=b"")
    assert_unified_error(response, 415, "AUDIO_INVALID")


def test_oversized_audio_is_cut_off(client, override_provider):
    override_provider(StubProvider())
    settings = get_settings()
    too_long = b"\x00\x00" * int(settings.speech_max_seconds * SAMPLE_RATE) + b"\x00\x00"
    response = post(client, audio=too_long)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "AUDIO_TOO_LARGE"


def test_audio_at_the_limit_is_accepted(client, override_provider):
    override_provider(StubProvider("ok"))
    settings = get_settings()
    exact = b"\x00\x00" * int(settings.speech_max_seconds * SAMPLE_RATE)
    response = post(client, audio=exact)
    assert response.status_code == 200, response.text


def test_transcript_is_capped_to_the_chat_message_limit(client, override_provider):
    override_provider(StubProvider("鱼" * 900))
    payload = post(client).json()
    assert len(payload["text"]) == 500


def test_no_audio_logged(client, override_provider, caplog):
    """The audio is speech; it must never reach a log line."""
    override_provider(StubProvider(error=SpeechFailed("failed")))
    with caplog.at_level("DEBUG"):
        post(client, audio=b"\x7f\x7e" * 8000)
    assert "speech.pcm" not in caplog.text
    assert "\x7f\x7e" not in caplog.text


@pytest.mark.parametrize("field", ["SPEECH_UNAVAILABLE", "SPEECH_FAILED", "SPEECH_EMPTY"])
def test_failure_messages_do_not_blame_the_photo_style(client, override_provider, field):
    """Guard against the CR-05 failure mode: telling the user it is their fault
    when the service broke. None of these may say "不清晰" / "格式"."""
    provider = {
        "SPEECH_UNAVAILABLE": NullSpeechProvider(),
        "SPEECH_FAILED": StubProvider(error=SpeechFailed("x")),
        "SPEECH_EMPTY": StubProvider(""),
    }[field]
    override_provider(provider)
    message = post(client).json()["detail"]["message"]
    for word in ("格式", "不清晰", "文件损坏"):
        assert word not in message, (word, message)
