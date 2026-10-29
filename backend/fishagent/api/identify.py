"""POST /api/agent/identify-fish — identify a fish from one uploaded photo.

Contract: docs/cr05-fish-identification.md. The image only ever lives in memory:
it is bounded while streaming, decoded and re-encoded by ``core.image_guard``,
sent to the vision model as a data-URI and then dropped. Neither the bytes nor
their base64 form is ever logged.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from fishagent.agent import llm
from fishagent.config import Settings, get_settings
from fishagent.core.image_guard import prepare_image
from fishagent.core.species import KNOWN_SPECIES, normalize_species
from fishagent.errors import ApiError
from fishagent.pilot import get_pilot_state
from fishagent.providers.vision_fish import (
    VisionFailure,
    VisionFish,
    VisionFishIdentifier,
    VisionUnavailable,
)
from fishagent.services.fish_activity import utc_timestamp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

MAX_NOTE_LENGTH = 100
MAX_TEXT_LENGTH = 200
MAX_BAITS = 4
MAX_BAIT_LENGTH = 20

UNIDENTIFIED_MESSAGE = (
    "未能识别出鱼的种类，请换一张更清晰的照片（建议鱼体完整、光线充足）。"
)

# One message per failure mode. None of these may say "unsupported format" or
# blame the photo: the upload was a valid image and the fault is ours.
FAILURE_MESSAGES: dict[VisionFailure, str] = {
    VisionFailure.TIMEOUT: (
        "图片识别服务响应超时，未能完成判断。"
        "这不是照片的问题，请稍后重试。"
    ),
    VisionFailure.UPSTREAM_ERROR: (
        "图片识别服务暂时不可用，未能完成判断。请稍后重试。"
    ),
    VisionFailure.EMPTY_ANSWER: (
        "图片识别服务没有返回有效结果，请稍后重试。"
    ),
    VisionFailure.UNPARSABLE_ANSWER: (
        "图片识别服务返回的结果无法解析，请稍后重试。"
    ),
}

# The model sometimes fills ``species`` with a placeholder even when it says
# ``identified=false`` ("无法识别", "不确定", "未知", ...). Those must never reach
# the client as a species name, so they force the "not identified" response.
# Exact matches cover short tokens; the substring list catches decorated forms
# such as "无法识别（照片模糊）".
PLACEHOLDER_SPECIES = frozenset(
    {
        "无法识别",
        "无法确定",
        "无法判断",
        "不能识别",
        "未识别",
        "不确定",
        "不清楚",
        "看不出",
        "未知",
        "非鱼",
        "不是鱼",
        "没有鱼",
        "无",
        "unknown",
        "n/a",
        "na",
        "none",
    }
)
PLACEHOLDER_SUBSTRINGS = (
    "无法识别",
    "无法确定",
    "无法判断",
    "不能识别",
    "不是鱼",
    "没有鱼",
    "看不出",
    "不确定",
    "未识别",
    "unknown",
)

_PUNCTUATION = " \t\r\n。.,，、!！?？:：;；()（）[]【】\"'“”‘’"

Confidence = Literal["high", "medium", "low"]


class IdentifyFishResponse(BaseModel):
    identified: bool
    species: str | None = None
    raw_species: str | None = None
    in_catalog: bool = False
    confidence: Confidence | None = None
    summary: str | None = None
    habits: str | None = None
    baits: list[str] = Field(default_factory=list)
    tips: str | None = None
    caveats: str | None = None
    mode: Literal["llm", "mock"]
    ai_disclosure: str = llm.AI_DISCLOSURE
    generated_at: str
    # Only present when nothing was identified; ``response_model_exclude_unset``
    # keeps it out of successful responses, as the contract's example requires.
    message: str | None = None


@router.post(
    "/identify-fish",
    response_model=IdentifyFishResponse,
    response_model_exclude_unset=True,
)
async def identify_fish(
    image: UploadFile = File(...),
    note: str | None = Form(default=None, max_length=MAX_NOTE_LENGTH),
) -> IdentifyFishResponse:
    settings = get_settings()
    trimmed_note = (note or "").strip() or None

    if not settings.mock_mode:
        # Fail fast before spending CPU on decoding an upload for a service
        # that could not answer anyway.
        _require_llm_configured()

    # Streaming read + Pillow verification happen for mock mode too, so both
    # modes enforce the same 413/415 contract.
    jpeg_bytes, media_type = await prepare_image(
        image,
        max_upload_bytes=settings.identify_max_upload_bytes,
        max_side=settings.identify_max_side,
        max_image_pixels=settings.identify_max_image_pixels,
        jpeg_quality=settings.identify_jpeg_quality,
        max_concurrent_decodes=settings.identify_max_concurrent_decodes,
        decode_memory_budget_mb=settings.identify_decode_memory_budget_mb,
        decode_bytes_per_pixel=settings.identify_decode_bytes_per_pixel,
    )

    if settings.mock_mode:
        return _mock_response(jpeg_bytes)

    identifier = get_vision_identifier(settings)
    if identifier is None:
        logger.warning("vision identifier unavailable despite an API key being configured")
        return _unidentified(mode="llm")

    # Quota is consumed in exactly one place: here, once per real vision call.
    # ``UpstreamQuotaExceeded`` is deliberately not caught — main.py's
    # quota_exceeded_handler turns it into 429 + Retry-After, matching chat.
    # With public access disabled ``get_pilot_state`` is None and the ledger is
    # not consulted at all.
    pilot_state = get_pilot_state(settings)
    if pilot_state is not None:
        pilot_state.ledger.consume("llm")

    logger.info("vision fish identification: normalised_image_bytes=%d", len(jpeg_bytes))
    try:
        result = await identifier.identify(
            jpeg_bytes,
            media_type=media_type,
            note=trimmed_note,
        )
    except VisionUnavailable as exc:
        # The service failed, not the photo. Saying "couldn't identify the fish"
        # here would blame the user's image for our own timeout and tell them to
        # do something (retake it) that cannot possibly help.
        logger.warning("vision fish identification unavailable: %s", exc.reason.value)
        raise ApiError(
            status_code=503,
            code="VISION_UNAVAILABLE",
            message=FAILURE_MESSAGES[exc.reason],
        ) from exc

    logger.info(
        "vision fish identification: identified=%s confidence=%s",
        result.identified,
        result.confidence,
    )
    return _to_response(result)


def _require_llm_configured() -> None:
    llm_settings = llm.load_llm_settings()
    if not llm_settings.api_key:
        raise ApiError(
            status_code=503,
            code="PROVIDER_NOT_CONFIGURED",
            message="图片识别服务未配置，请先设置 LLM_API_KEY",
        )


_VISION_CACHE: tuple[tuple[str, str, str, float], VisionFishIdentifier] | None = None


def get_vision_identifier(settings: Settings) -> VisionFishIdentifier | None:
    """Build (and cache) the vision adapter from the shared LLM settings.

    Reusing ``load_llm_settings`` means one ``LLM_API_KEY`` covers chat and
    vision, and Mock mode never reaches this function at all.
    """
    global _VISION_CACHE
    llm_settings = llm.load_llm_settings()
    if not llm_settings.api_key:
        return None
    model = (settings.llm_vision_model or "").strip() or llm_settings.model
    timeout = float(settings.identify_timeout_seconds)
    key = (llm_settings.api_key, llm_settings.base_url, model, timeout)
    if _VISION_CACHE is not None and _VISION_CACHE[0] == key:
        return _VISION_CACHE[1]
    try:
        from openai import AsyncOpenAI
    except ImportError:  # pragma: no cover - openai is a hard dependency
        logger.warning("openai package unavailable; fish identification disabled")
        return None
    client = AsyncOpenAI(
        api_key=llm_settings.api_key,
        base_url=llm_settings.base_url,
        timeout=timeout,
    )
    identifier = VisionFishIdentifier(client, model, timeout_seconds=timeout)
    _VISION_CACHE = (key, identifier)
    return identifier


def _to_response(result: VisionFish | None) -> IdentifyFishResponse:
    if result is None or not result.identified:
        # Contract: identified=false must null out species/raw_species even if
        # the model put a placeholder such as "无法识别" into them.
        return _unidentified(mode="llm")

    raw_species = _clip(result.species, MAX_TEXT_LENGTH)
    if raw_species is None or _is_placeholder(raw_species):
        return _unidentified(mode="llm")

    normalized = normalize_species([raw_species], limit=1)
    if normalized:
        species = normalized[0]
        in_catalog = species in KNOWN_SPECIES
    else:
        # Unknown to the catalog: keep the model's wording but flag it, so the
        # UI can say the species is outside the common list.
        species = raw_species
        in_catalog = False

    summary = _clip(result.summary, MAX_TEXT_LENGTH)
    habits = _clip(result.habits, MAX_TEXT_LENGTH)
    tips = _clip(result.tips, MAX_TEXT_LENGTH)
    caveats = _clip(result.caveats, MAX_TEXT_LENGTH)
    baits = _clean_baits(result.baits)

    if _violates_any(species, summary, habits, tips, caveats, *baits):
        # A promise of catches anywhere in the text degrades the whole answer:
        # never ship a partially sanitised identification.
        logger.warning("fish identification text hit guardrails; degrading to unidentified")
        return _unidentified(mode="llm")

    return IdentifyFishResponse(
        identified=True,
        species=species,
        raw_species=raw_species,
        in_catalog=in_catalog,
        confidence=result.confidence,
        summary=summary,
        habits=habits,
        baits=baits,
        tips=tips,
        caveats=caveats,
        mode="llm",
        ai_disclosure=llm.AI_DISCLOSURE,
        generated_at=utc_timestamp(),
    )


def _unidentified(*, mode: Literal["llm", "mock"]) -> IdentifyFishResponse:
    return IdentifyFishResponse(
        identified=False,
        species=None,
        raw_species=None,
        in_catalog=False,
        confidence=None,
        summary=None,
        habits=None,
        baits=[],
        tips=None,
        caveats=None,
        mode=mode,
        ai_disclosure=llm.AI_DISCLOSURE,
        generated_at=utc_timestamp(),
        message=UNIDENTIFIED_MESSAGE,
    )


def _is_placeholder(value: str) -> bool:
    text = value.strip(_PUNCTUATION).lower()
    if not text or text in PLACEHOLDER_SPECIES:
        return True
    return any(token in text for token in PLACEHOLDER_SUBSTRINGS)


def _violates_any(*values: Any) -> bool:
    return any(llm.violates_guardrails(str(value)) for value in values if value)


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit]


def _clean_baits(values: list[str]) -> list[str]:
    baits: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clip(value, MAX_BAIT_LENGTH)
        if not text or text in seen:
            continue
        seen.add(text)
        baits.append(text)
        if len(baits) >= MAX_BAITS:
            break
    return baits


# --- mock mode ---------------------------------------------------------------

_MOCK_PROFILES = (
    (
        "鲫鱼",
        "high",
        "鲫鱼是常见的淡水底层鱼，适应力强。",
        "喜栖水底，偏爱安静、有水草或缓流的环境。",
        ("蚯蚓", "红虫", "商品饵（腥香）"),
        "钓底为主，注意避开高温正午。",
        "仅根据单张照片判断，角度与光线可能影响结果。",
    ),
    (
        "鲤鱼",
        "medium",
        "鲤鱼体型较大，常在水底拱泥觅食。",
        "警觉性高，偏爱有障碍物或深浅交界的区域。",
        ("玉米", "商品饵（薯香）", "蚯蚓"),
        "打窝后耐心守钓，避免频繁提竿。",
        "仅根据单张照片判断，角度与光线可能影响结果。",
    ),
    (
        "草鱼",
        "low",
        "草鱼是典型的草食性淡水鱼，活动范围广。",
        "多在中上层活动，喜欢水草和嫩叶。",
        ("嫩草", "玉米", "商品饵（谷香）"),
        "可尝试钓浮或半水，注意保持安静。",
        "仅根据单张照片判断，角度与光线可能影响结果。",
    ),
)


def _mock_response(jpeg_bytes: bytes) -> IdentifyFishResponse:
    """Deterministic mock: the same image always yields the same profile."""
    digest = hashlib.sha256(jpeg_bytes).digest()
    species, confidence, summary, habits, baits, tips, caveats = _MOCK_PROFILES[
        digest[0] % len(_MOCK_PROFILES)
    ]
    return IdentifyFishResponse(
        identified=True,
        species=species,
        raw_species=species,
        in_catalog=True,
        confidence=confidence,
        summary=summary,
        habits=habits,
        baits=list(baits),
        tips=tips,
        caveats=caveats,
        mode="mock",
        ai_disclosure=llm.AI_DISCLOSURE,
        generated_at=utc_timestamp(),
    )
