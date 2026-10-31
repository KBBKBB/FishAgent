"""POST /api/agent/transcribe — turn one spoken utterance into text.

Contract: docs/cr06-voice-input.md.

Privacy rules mirror the image endpoint: the audio lives in memory only, is
never written to disk, never cached and never logged. Neither the bytes nor the
recognised text may appear in a log line.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from fishagent.agent import llm
from fishagent.config import get_settings
from fishagent.deps import get_speech_provider
from fishagent.errors import ApiError
from fishagent.providers.speech_none import (
    SpeechFailed,
    SpeechProvider,
    SpeechUnavailable,
)
from fishagent.services.fish_activity import utc_timestamp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
MAX_MESSAGE_LENGTH = 500

# One message per failure, and none of them blames the user. "Didn't catch
# that" is reserved for genuinely empty audio; an engine that failed must not
# be reported as the user mumbling.
FAILURE_MESSAGES = {
    "SPEECH_UNAVAILABLE": "语音识别暂未启用，请直接输入文字。",
    "SPEECH_FAILED": "语音识别处理失败，请重试或直接输入文字。",
    "SPEECH_TIMEOUT": "语音识别超时，请重试或直接输入文字。",
}
EMPTY_SPEECH_MESSAGE = "没有听清，请靠近麦克风再说一次。"


class TranscriptResponse(BaseModel):
    text: str
    provider: str
    ai_disclosure: str = llm.AI_DISCLOSURE
    generated_at: str


def _too_large() -> ApiError:
    seconds = get_settings().speech_max_seconds
    return ApiError(
        status_code=413,
        code="AUDIO_TOO_LARGE",
        message=f"录音过长，请控制在 {seconds:g} 秒以内。",
    )


def _bad_audio(message: str) -> ApiError:
    return ApiError(status_code=415, code="AUDIO_INVALID", message=message)


@router.post("/transcribe", response_model=TranscriptResponse)
async def transcribe(
    audio: UploadFile = File(..., description="16 kHz mono 16-bit PCM"),
    sample_rate: int = Form(default=SAMPLE_RATE),
    provider: SpeechProvider = Depends(get_speech_provider),
) -> TranscriptResponse:
    settings = get_settings()

    if sample_rate != SAMPLE_RATE:
        raise _bad_audio(f"音频采样率必须为 {SAMPLE_RATE} Hz。")

    # Bound while streaming: a Content-Length header is a claim, not a promise,
    # and the same reasoning applies here as to image uploads.
    max_bytes = int(settings.speech_max_seconds * SAMPLE_RATE * BYTES_PER_SAMPLE)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await audio.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large()
        chunks.append(chunk)
    pcm = b"".join(chunks)

    if not pcm:
        raise _bad_audio("没有收到音频数据。")

    try:
        text = await provider.transcribe(pcm, sample_rate)
    except SpeechUnavailable:
        logger.warning("speech provider unavailable")
        raise ApiError(
            status_code=501,
            code="SPEECH_UNAVAILABLE",
            message=FAILURE_MESSAGES["SPEECH_UNAVAILABLE"],
        ) from None
    except SpeechFailed as exc:
        logger.warning("speech provider failed: %s", type(exc).__name__)
        raise ApiError(
            status_code=422,
            code="SPEECH_FAILED",
            message=FAILURE_MESSAGES["SPEECH_FAILED"],
        ) from None
    except Exception:
        # Never include the exception text: it may quote the audio or the
        # recognised speech.
        logger.warning("speech provider raised unexpectedly", exc_info=False)
        raise ApiError(
            status_code=503,
            code="SPEECH_UNAVAILABLE",
            message=FAILURE_MESSAGES["SPEECH_UNAVAILABLE"],
        ) from None

    text = (text or "").strip()
    if not text:
        # Recogniser ran and heard nothing. A distinct code, because the user
        # can act on this one ("speak closer") -- unlike an engine failure.
        raise ApiError(status_code=422, code="SPEECH_EMPTY", message=EMPTY_SPEECH_MESSAGE)

    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]

    return TranscriptResponse(
        text=text,
        provider=getattr(provider, "name", "unknown"),
        generated_at=utc_timestamp(),
    )
