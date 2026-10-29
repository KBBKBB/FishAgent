"""OpenAI-compatible vision call that identifies the fish in one photo.

The endpoint is untrusted input: it may time out, return prose instead of JSON,
or answer with an empty ``content``. Failures are reported as a typed
``VisionFailure`` so the API can tell the user what actually happened —
"the service timed out" and "no fish in this photo" are different answers, and
collapsing them onto "couldn't identify the fish" blames the user's photo for
our own outage.

Known trap: some reasoning-capable deployments put the whole answer in
``message.reasoning_content`` and leave ``message.content`` empty. That content
is chain-of-thought, not the answer, so an empty ``content`` is treated as a
failure; ``reasoning_content`` is never parsed as the result.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

MAX_TOKENS = 800
TEMPERATURE = 0.2
CONFIDENCE_VALUES = ("high", "medium", "low")

# Unknown names are deliberately allowed here: the API keeps the model's raw
# answer and only flags it as out-of-catalog, so the prompt must not force the
# model to pick from a list it does not know.
SYSTEM_PROMPT = (
    "你是 FishAgent 的鱼类识别助手。用户会提供一张照片，请判断照片中的鱼种。"
    "要求：1) 只依据照片中可见的特征判断，不得编造；"
    "2) 拿不准或照片中没有鱼时，identified 必须为 false，并把 species 设为 null；"
    "3) confidence 只能是 high、medium、low；"
    "4) 不承诺渔获，禁止“必上鱼”“保证爆护”“百分百”等表述；"
    "5) 所有文本字段用中文，尽量简短。"
    "只输出 JSON，不要解释，格式："
    '{"identified":true,"species":"鲫鱼","confidence":"high",'
    '"summary":"简要鱼类知识","habits":"习性","baits":["蚯蚓"],'
    '"tips":"垂钓提示","caveats":"判断局限"}。'
)

_FENCED_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class VisionFailure(str, Enum):
    """Why an identification attempt produced no answer.

    Each value maps to a different user-facing message, because "the model
    timed out" and "there is no fish in the picture" call for different
    actions and different blame.
    """

    TIMEOUT = "timeout"
    UPSTREAM_ERROR = "upstream_error"
    EMPTY_ANSWER = "empty_answer"
    UNPARSABLE_ANSWER = "unparsable_answer"


class VisionUnavailable(Exception):
    """The call itself failed; no answer was obtained.

    Deliberately an exception rather than a ``None`` return so it cannot be
    confused with "the model looked and saw no fish".
    """

    def __init__(self, reason: VisionFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass
class VisionFish:
    """Raw model answer; the API layer normalises and bounds every field."""

    identified: bool
    species: str | None = None
    confidence: str | None = None
    summary: str | None = None
    habits: str | None = None
    baits: list[str] = field(default_factory=list)
    tips: str | None = None
    caveats: str | None = None


class VisionFishIdentifier:
    """Wraps an AsyncOpenAI client to turn a photo into a species guess.

    An unsure answer comes back as ``None``. A failure raises
    ``VisionUnavailable`` carrying the reason, so the endpoint can tell the
    user *why* nothing was identified instead of blaming the photo.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._client = client
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self._model)

    async def identify(
        self,
        jpeg_bytes: bytes,
        *,
        media_type: str = "image/jpeg",
        note: str | None = None,
    ) -> VisionFish | None:
        if not self.enabled or not jpeg_bytes:
            return None
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    messages=_build_messages(jpeg_bytes, media_type, note),
                ),
                timeout=self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                logger.warning(
                    "vision fish identification timed out after %.0fs",
                    self._timeout_seconds,
                )
                raise VisionUnavailable(VisionFailure.TIMEOUT) from exc
            # Connection errors, HTTP errors and auth failures: our fault, not
            # the user's photo. The route answers 503, not "couldn't identify".
            logger.warning("vision fish identification call failed", exc_info=True)
            raise VisionUnavailable(VisionFailure.UPSTREAM_ERROR) from exc

        content = _content_of(response)
        if not content:
            # Empty content means failure. Do NOT fall back to
            # message.reasoning_content: it is the model's scratchpad, not an
            # answer, and returning it would surface hallucinated species.
            logger.warning("vision fish identification returned empty content")
            raise VisionUnavailable(VisionFailure.EMPTY_ANSWER)
        result = _parse_payload(content)
        if result is None:
            logger.warning("vision fish identification returned an unparsable answer")
            raise VisionUnavailable(VisionFailure.UNPARSABLE_ANSWER)
        return result


_TIMEOUT_EXCEPTION_NAMES = (("httpx", "TimeoutException"), ("openai", "APITimeoutError"))


def _is_timeout(exc: BaseException, *, _depth: int = 0) -> bool:
    """Whether this exception means "we waited too long", however it surfaced.

    ``TimeoutError`` alone is not enough. ``asyncio.wait_for`` raises the
    builtin on 3.11+, but the SDK's own ``APITimeoutError`` inherits from
    ``openai.APIError``, and the ``httpx.ReadTimeout`` underneath inherits from
    ``httpx.TimeoutException`` — neither is a ``TimeoutError``. Without this
    the slower of the two timers would be reported as "service unavailable"
    instead of "timed out", which is a different problem with a different fix.
    """
    if isinstance(exc, TimeoutError):
        return True
    for module_name, class_name in _TIMEOUT_EXCEPTION_NAMES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover - both are hard dependencies
            continue
        cls = getattr(module, class_name, None)
        if isinstance(cls, type) and isinstance(exc, cls):
            return True
    # SDKs wrap the transport error, so the timeout often sits in the cause
    # chain. Bounded depth: ``__cause__`` can form a cycle.
    if _depth < 4 and isinstance(exc.__cause__, BaseException):
        if _is_timeout(exc.__cause__, _depth=_depth + 1):
            return True
    return "timeout" in type(exc).__name__.lower()


def _build_messages(
    jpeg_bytes: bytes,
    media_type: str,
    note: str | None,
) -> list[dict[str, Any]]:
    encoded = base64.b64encode(jpeg_bytes).decode("ascii")
    data_uri = f"data:{media_type};base64,{encoded}"
    text = "请识别这张照片中的鱼种，并按要求的 JSON 格式回答。"
    trimmed_note = (note or "").strip()
    if trimmed_note:
        text += f"\n用户补充说明：{trimmed_note}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        },
    ]


def _content_of(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return ""
    return content.strip() if isinstance(content, str) else ""


def _parse_payload(content: str) -> VisionFish | None:
    text = content.strip()
    fenced = _FENCED_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    identified = payload.get("identified")
    if not isinstance(identified, bool):
        # Ambiguous answers are treated as "not identified" rather than guessed.
        identified = False

    confidence = payload.get("confidence")
    confidence = confidence.strip().lower() if isinstance(confidence, str) else ""
    if confidence not in CONFIDENCE_VALUES:
        confidence = None

    baits = payload.get("baits")
    if isinstance(baits, str):
        baits = [baits]
    if not isinstance(baits, list):
        baits = []

    return VisionFish(
        identified=identified,
        species=_text(payload.get("species")),
        confidence=confidence,
        summary=_text(payload.get("summary")),
        habits=_text(payload.get("habits")),
        baits=[text for item in baits if (text := _text(item))],
        tips=_text(payload.get("tips")),
        caveats=_text(payload.get("caveats")),
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    text = value.strip()
    return text or None
