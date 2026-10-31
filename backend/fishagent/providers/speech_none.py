"""Speech-to-text provider protocol.

Mirrors ``SpeciesProvider``: a narrow protocol plus swappable implementations,
so the transport (HTTP endpoint) and the engine (Vosk today, a cloud service
later) stay independent. Tests inject fakes through the dependency seam.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class SpeechError(RuntimeError):
    """Base for transcription failures. ``code`` is stable, for the client."""

    code = "TRANSCRIPTION_FAILED"


class SpeechUnavailable(SpeechError):
    """The engine cannot run at all (not installed, model missing)."""

    code = "SPEECH_UNAVAILABLE"


class SpeechFailed(SpeechError):
    """The engine ran but could not produce text."""

    code = "SPEECH_FAILED"


@runtime_checkable
class SpeechProvider(Protocol):
    name: str

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        """Return recognised text, or raise SpeechError.

        ``pcm`` is signed 16-bit little-endian mono. Empty string means "ran
        fine, found no speech" -- callers must distinguish that from a failure,
        because the two deserve different messages to the user.
        """
        ...


class NullSpeechProvider:
    """The feature is switched off.

    Mirrors NullSpeciesProvider: reporting "nothing heard" here would imply we
    listened. The endpoint answers 501 instead.
    """

    name = "none"
    resolves = False

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:  # noqa: ARG002
        raise SpeechUnavailable("语音识别未启用")
