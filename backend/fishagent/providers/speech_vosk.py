"""Offline speech recognition via Vosk.

Chosen over the browser's Web Speech API because that path is unusable here:
Chrome and Edge both need Google's backend, which does not answer from this
host (measured 8 s timeouts). Vosk runs locally, costs nothing and keeps the
audio on the machine.

The engine is synchronous and CPU-bound, so every call goes through a thread.
Running it inline would block the event loop for the whole utterance -- on this
box the audio decode alone is tens of milliseconds per second of speech, which
is enough to stall every other request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from fishagent.providers.speech_none import SpeechFailed, SpeechUnavailable

logger = logging.getLogger(__name__)

# 16 kHz mono 16-bit is what the browser produces and what the small Chinese
# model expects. A mismatch is a bug in the caller, not a user error.
EXPECTED_SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 2

_HAN_START = "一"
_HAN_END = "鿿"


def join_han_tokens(text: str) -> str:
    """Remove the spaces Vosk puts between Chinese words.

    Vosk tokenises Chinese into words and joins the result with spaces, so
    "鲢鳙用什么饵料" comes back as "鲢 鳙 用 什么 饵料". Everything downstream
    (intent regexes, species matching) reads natural sentences, so a space
    between two Han characters breaks matching in two ways: multi-character
    species split apart ("鲢 鳙" is no longer 鲢鳙), and phrase patterns such
    as 用什么 stop matching.

    Only Han-Han boundaries are joined. A Latin or numeric token keeps its
    separators, so "16 度" does not become "16度" glued to the next word.
    """
    tokens = [token for token in text.split(" ") if token]
    if not tokens:
        return ""
    joined = tokens[0]
    for token in tokens[1:]:
        if _is_han(joined[-1]) and _is_han(token[0]):
            joined += token
        else:
            joined += " " + token
    return joined


def _is_han(char: str) -> bool:
    return _HAN_START <= char <= _HAN_END


class VoskSpeechProvider:
    """Wraps a Vosk model loaded once at startup.

    The model is loaded lazily and cached: constructing a ``KaldiRecognizer``
    per request is fine, but re-reading a 44 MB model per request is not.
    """

    name = "vosk"

    def __init__(self, model_path: Path | str) -> None:
        self._model_path = Path(model_path)
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        # Double-checked so concurrent first requests load the model once.
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from vosk import Model, SetLogLevel
            except ImportError as exc:
                raise SpeechUnavailable(
                    "语音识别组件未安装（缺少 vosk），请先安装依赖"
                ) from exc
            # Vosk logs each decoded chunk to stderr at default verbosity.
            SetLogLevel(-1)
            if not self._model_path.exists():
                raise SpeechUnavailable(
                    f"语音识别模型不存在：{self._model_path}"
                )
            try:
                self._model = Model(str(self._model_path))
            except Exception as exc:  # noqa: BLE001 - engine init can fail many ways
                logger.warning("vosk model load failed", exc_info=True)
                raise SpeechUnavailable("语音识别模型加载失败") from exc
            return self._model

    def _recognise(self, pcm: bytes, sample_rate: int) -> str:
        if sample_rate != EXPECTED_SAMPLE_RATE:
            raise SpeechFailed(
                f"音频采样率应为 {EXPECTED_SAMPLE_RATE} Hz，实际 {sample_rate} Hz"
            )
        if len(pcm) % _BYTES_PER_SAMPLE:
            # An odd byte count means the client cut a sample in half. Decoding
            # it would shift every subsequent sample.
            raise SpeechFailed("音频数据不完整")

        from vosk import KaldiRecognizer

        model = self._load()
        try:
            recognizer = KaldiRecognizer(model, sample_rate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vosk recognizer init failed", exc_info=True)
            raise SpeechFailed("语音识别初始化失败") from exc

        recognizer.AcceptWaveform(pcm)
        raw = recognizer.FinalResult()
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            # Never log the payload: it is the recognised speech.
            logger.warning("vosk returned unparsable result")
            raise SpeechFailed("语音识别结果无法解析") from None
        text = payload.get("text")
        if not isinstance(text, str):
            return ""
        return join_han_tokens(text.strip())

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        return await asyncio.to_thread(self._recognise, pcm, sample_rate)


def model_available(path: Path | str) -> bool:
    """Whether a model directory looks usable, for a startup log line."""
    # Guard the empty string explicitly: Path("") is Path("."), so an unset
    # model path would otherwise report the current working directory -- which
    # is of course non-empty -- as a valid model.
    if not str(path).strip():
        return False
    target = Path(path)
    return target.is_dir() and any(target.iterdir())
