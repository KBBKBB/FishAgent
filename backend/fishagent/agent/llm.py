"""OpenAI-compatible LLM adapter and deterministic fallback routing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

AI_DISCLOSURE = "本内容由 AI 生成，仅供参考，不承诺渔获。"

ALLOWED_SPECIES = ("鲫鱼", "鲤鱼", "草鱼", "鲢鳙")
SPECIES_ALIASES = (
    ("鲫鱼", "鲫鱼"),
    ("鲤鱼", "鲤鱼"),
    ("草鱼", "草鱼"),
    ("鲢鳙", "鲢鳙"),
    ("胖头鱼", "鲢鳙"),
    ("胖头", "鲢鳙"),
    ("花鲢", "鲢鳙"),
    ("鲫", "鲫鱼"),
    ("鲤", "鲤鱼"),
)

INTENT_PATTERNS = {
    "fish": re.compile(r"气压|鱼情|鱼口|适合钓|能钓|好钓|活跃|天气|出钓|评分|开口|鱼获"),
    "time": re.compile(r"几点|时段|明早|早上|清晨|傍晚|什么时候|最佳时间|窗口"),
    "spots": re.compile(r"附近|哪里|钓位|钓点|野钓|推荐|车程|水库|湖泊|野塘|河流|钓场"),
}
INTENT_ORDER = ("fish", "time", "spots")

GUIDE_REPLY = (
    "我可以帮你分析当前鱼情与气压、推荐附近钓位，或给出最佳出钓时段。"
    "试试问「今天气压适合钓鱼吗？」「附近哪里野钓好？」「明早几点去最好？」"
)

INTENT_SYSTEM_PROMPT = (
    "你是 FishAgent 的意图分类器。可选意图："
    "fish=鱼情/气压/鱼口/是否适合钓鱼；"
    "time=最佳出钓时段/几点去；"
    "spots=附近钓位/钓点/野钓推荐。"
    "可返回多个意图，无匹配返回空数组。只输出 JSON，不要解释："
    '{"intents":["fish"],"species":null}。'
    "species 仅允许 鲫鱼、鲤鱼、草鱼、鲢鳙；用户未提及时为 null。"
)

ANSWER_SYSTEM_PROMPT = (
    "你是 FishAgent 钓鱼助手。请只依据用户问题与工具数据，用中文给出 2–5 句简洁、可执行的建议。"
    "要求：1) 不承诺渔获，禁止“必上鱼”“保证爆护”“百分百”“绝不空军”等表述；"
    "2) 不逐项播报天气预报，只提炼与钓鱼相关的结论；"
    "3) 鱼情类回答包含评分/档位、关键因子和最佳时段；钓位类回答包含首选钓位、往返时间与理由；"
    "4) 不编造数据中没有的信息；5) 有风险提示时说明原因；"
    "6) 使用纯文本，不要使用 Markdown 标记（**、#、列表符号等）。"
)


@dataclass(frozen=True)
class LLMSettings:
    mock_mode: bool = True
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 30.0


def load_llm_settings() -> LLMSettings:
    try:
        from fishagent import config as config_module
    except ImportError:
        logger.warning("fishagent.config unavailable; LLM is disabled")
        return LLMSettings()

    settings = getattr(config_module, "settings", None)
    if settings is None:
        getter = getattr(config_module, "get_settings", None)
        if callable(getter):
            settings = getter()
    if settings is None:
        return LLMSettings()

    api_key = getattr(settings, "llm_api_key", "") or ""
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()

    return LLMSettings(
        mock_mode=bool(getattr(settings, "mock_mode", True)),
        api_key=str(api_key).strip(),
        base_url=str(getattr(settings, "llm_base_url", "https://api.openai.com/v1"))
        or "https://api.openai.com/v1",
        model=str(getattr(settings, "llm_model", "gpt-4o-mini")) or "gpt-4o-mini",
        timeout_seconds=float(getattr(settings, "llm_timeout_seconds", 30.0) or 30.0),
    )


def classify_intents(message: str) -> list[str]:
    text = message or ""
    found = {name for name, pattern in INTENT_PATTERNS.items() if pattern.search(text)}
    return [name for name in INTENT_ORDER if name in found]


def normalize_species(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in ALLOWED_SPECIES:
        return text
    for token, canonical in SPECIES_ALIASES:
        if token in text:
            return canonical
    return None


PROMISE_PATTERN = re.compile(r"必上鱼|保证爆护|保证上鱼|包爆护|必爆护|百分百|100%|绝不空军")

MAX_REPLY_SENTENCES = 5
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])")
_SENTENCE_PUNCT = re.compile(r"[。！？!?]+")


def violates_guardrails(text: str) -> bool:
    return bool(PROMISE_PATTERN.search(text or ""))


class LLMClient:
    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self._client: AsyncOpenAI | None = None
        if self.enabled:
            self._client = AsyncOpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.timeout_seconds,
            )

    @property
    def enabled(self) -> bool:
        return not self.settings.mock_mode and bool(self.settings.api_key)

    async def classify(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[list[str], str | None] | None:
        if not self.enabled or self._client is None:
            return None

        messages: list[dict[str, str]] = [{"role": "system", "content": INTENT_SYSTEM_PROMPT}]
        for item in (history or [])[-4:]:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)[:500]})
        messages.append({"role": "user", "content": message})

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=0,
                max_tokens=120,
            )
        except Exception:
            logger.warning("LLM intent classification failed", exc_info=True)
            return None

        content = _message_content(response)
        if not content:
            return None
        return _parse_intent_payload(content)

    async def compose(
        self,
        *,
        message: str,
        location_name: str | None,
        intents: list[str],
        species: str | None,
        fish_activity: dict[str, Any] | None,
        spots: dict[str, Any] | None,
    ) -> str | None:
        if not self.enabled or self._client is None:
            return None

        context = {
            "question": message,
            "location": location_name or "用户位置",
            "intents": intents,
            "species": species,
            "fish_activity": _trim_fish_activity(fish_activity),
            "spots": _trim_spots(spots),
        }
        try:
            response = await self._client.chat.completions.create(
                model=self.settings.model,
                messages=[
                    {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                temperature=0.4,
                max_tokens=500,
            )
        except Exception:
            logger.warning("LLM answer composition failed", exc_info=True)
            return None

        content = _message_content(response)
        if not content or violates_guardrails(content):
            return None
        return content.strip()


_LLM_CLIENT: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        _LLM_CLIENT = LLMClient(load_llm_settings())
    return _LLM_CLIENT


def compose_fallback_reply(
    *,
    intents: list[str],
    fish_activity: dict[str, Any] | None,
    spots: dict[str, Any] | None,
) -> str:
    if not intents:
        return GUIDE_REPLY

    wants_fish = "fish" in intents or "time" in intents
    wants_spots = "spots" in intents
    time_focus = "time" in intents and "fish" not in intents

    fish_sentences: list[tuple[str, bool]] = []
    if wants_fish:
        if isinstance(fish_activity, dict):
            fish_sentences = _fish_sentences(fish_activity, time_focus=time_focus)
        else:
            fish_sentences = [("鱼情数据暂时不可用，请稍后再试。", True)]

    spots_sentences: list[str] = []
    if wants_spots:
        if isinstance(spots, dict):
            spots_sentences = _spots_sentences(spots)
        else:
            spots_sentences = ["钓位推荐暂时不可用，请稍后再试。"]

    sentences = _merge_sentences(fish_sentences, spots_sentences)
    if not sentences:
        return GUIDE_REPLY
    if len(sentences) < 2:
        sentences.append("建议结合实时天气和现场情况安排出钓。")
    return _limit_sentences("".join(sentences))


def _message_content(response: Any) -> str | None:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) and content.strip() else None


def _parse_intent_payload(content: str) -> tuple[list[str], str | None] | None:
    text = content.strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
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
    raw = payload.get("intents") or []
    if isinstance(raw, str):
        raw = [raw]
    intents = [name for name in INTENT_ORDER if name in raw]
    return intents, normalize_species(payload.get("species"))


def _trim_fish_activity(fish: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(fish, dict):
        return None
    factors = fish.get("top_factors") or fish.get("factors") or []
    alerts = fish.get("alerts") or []
    return {
        "score": fish.get("score"),
        "band": fish.get("band"),
        "advice": fish.get("advice"),
        "recommendation": fish.get("recommendation"),
        "top_factors": [
            {
                "name": factor.get("name"),
                "impact": factor.get("impact"),
                "detail": factor.get("detail"),
            }
            for factor in factors[:3]
            if isinstance(factor, dict)
        ],
        "best_windows": fish.get("best_windows") or [],
        "water_depth": fish.get("water_depth"),
        "alerts": [
            {"level": alert.get("level"), "message": alert.get("message")}
            for alert in alerts
            if isinstance(alert, dict)
        ][:4],
    }


def _trim_spots(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    spots = []
    for spot in (payload.get("spots") or [])[:3]:
        if not isinstance(spot, dict):
            continue
        spots.append(
            {
                "name": spot.get("name"),
                "water_type": spot.get("water_type"),
                "drive_minutes_one_way": spot.get("drive_minutes_one_way"),
                "drive_seconds_round_trip": spot.get("drive_seconds_round_trip"),
                "total_score": spot.get("total_score"),
                "reasons": spot.get("reasons") or [],
                "entry_precision": spot.get("entry_precision"),
            }
        )
    return {
        "spots": spots,
        "filtered": payload.get("filtered") or {},
        "meta": {"traffic_basis": (payload.get("meta") or {}).get("traffic_basis")},
    }


def _limit_sentences(text: str, limit: int = MAX_REPLY_SENTENCES) -> str:
    parts = [part for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    return "".join(parts[:limit])


def _sentence_body(value: Any) -> str:
    return _SENTENCE_PUNCT.sub("；", str(value)).strip("； ")


def _fish_sentences(fish: dict[str, Any], *, time_focus: bool) -> list[tuple[str, bool]]:
    """Priority order: conclusion > forced alerts > window > factors > depth."""
    recommendation = fish.get("recommendation") or fish.get("advice")
    score = fish.get("score")
    band = fish.get("band")
    if score is not None:
        conclusion = f"当前鱼口评分 {score} 分（{band or '待评估'}）"
        advice = _sentence_body(recommendation) if recommendation else ""
        if advice:
            conclusion += f"，{advice}"
        sentences: list[tuple[str, bool]] = [(conclusion + "。", True)]
    elif recommendation and _sentence_body(recommendation):
        sentences = [(_sentence_body(recommendation) + "。", True)]
    else:
        sentences = [("当前鱼情数据已返回。", True)]

    alerts = [
        body
        for body in (_sentence_body(item) for item in _alert_messages(fish.get("alerts")))
        if body
    ]
    if alerts:
        sentences.append(("安全提示：" + "；".join(alerts) + "。", True))

    windows = _format_windows(fish.get("best_windows"))
    if time_focus:
        if windows:
            sentences.append((f"建议优先安排 {windows}。", False))
        else:
            sentences.append(("暂未给出明确窗口，建议选择清晨或傍晚出钓。", False))
    elif windows:
        sentences.append((f"最佳时段：{windows}。", False))

    factor_sentence = _factor_sentence(fish.get("top_factors") or fish.get("factors") or [])
    if factor_sentence:
        sentences.append((factor_sentence, False))

    depth = _sentence_body(fish.get("water_depth") or "")
    if depth:
        sentences.append((f"水深建议：{depth}。", False))

    return sentences


def _factor_sentence(factors: list[Any]) -> str | None:
    positive = next(
        (item for item in factors if isinstance(item, dict) and item.get("impact") == "positive"),
        None,
    )
    negative = next(
        (item for item in factors if isinstance(item, dict) and item.get("impact") == "negative"),
        None,
    )
    pieces: list[str] = []
    if positive and positive.get("detail"):
        pieces.append(
            f"主要利好是{positive.get('name', '关键因子')}：{_sentence_body(positive['detail'])}"
        )
    if negative and negative.get("detail"):
        pieces.append(
            f"需要留意{negative.get('name', '不利因子')}：{_sentence_body(negative['detail'])}"
        )
    if not pieces:
        first = next(
            (item for item in factors if isinstance(item, dict) and item.get("detail")),
            None,
        )
        if first:
            name = first.get("name", "主要因子")
            pieces.append(f"关键因子是{name}：{_sentence_body(first['detail'])}")
    return "；".join(pieces) + "。" if pieces else None


def _merge_sentences(
    fish_sentences: list[tuple[str, bool]],
    spots_sentences: list[str],
) -> list[str]:
    if not spots_sentences:
        return _take_sentences(fish_sentences, MAX_REPLY_SENTENCES)
    if not fish_sentences:
        return spots_sentences[:MAX_REPLY_SENTENCES]

    core = spots_sentences[:2]
    slots = MAX_REPLY_SENTENCES - len(core)
    selected = _take_sentences(fish_sentences, slots)
    remaining = MAX_REPLY_SENTENCES - len(selected) - len(core)
    return selected + core + spots_sentences[2:][: max(remaining, 0)]


def _take_sentences(entries: list[tuple[str, bool]], slots: int) -> list[str]:
    selected = [text for text, mandatory in entries if mandatory]
    optional = [text for text, mandatory in entries if not mandatory]
    selected.extend(optional[: max(slots - len(selected), 0)])
    return selected


def _spots_sentences(payload: dict[str, Any]) -> list[str]:
    items = payload.get("spots") or []
    filtered = payload.get("filtered") or {}
    if not items:
        return ["附近暂未找到满足往返 2 小时内且非禁钓的钓位，建议调整位置后再试。"]

    first = items[0] if isinstance(items[0], dict) else {}
    sentences: list[str] = []
    exclusions: list[str] = []
    if filtered.get("forbidden") is not None:
        exclusions.append(f"禁钓排除 {filtered['forbidden']} 个")
    if filtered.get("over_two_hours") is not None:
        exclusions.append(f"往返超 2 小时 {filtered['over_two_hours']} 个")
    summary = f"附近筛选出 {len(items)} 个满足条件的钓位"
    if exclusions:
        summary += "（" + "、".join(exclusions) + "）"
    sentences.append(summary + "。")

    sentence = f"首选「{first.get('name', '推荐钓位')}」"
    if first.get("water_type"):
        sentence += f"，类型为{first['water_type']}"
    if first.get("drive_minutes_one_way") is not None:
        sentence += f"，单程约 {first['drive_minutes_one_way']} 分钟"
    if first.get("drive_seconds_round_trip") is not None:
        round_trip_minutes = round(float(first["drive_seconds_round_trip"]) / 60)
        sentence += f"，往返约 {round_trip_minutes} 分钟"
    if first.get("total_score") is not None:
        sentence += f"，综合分 {first['total_score']}"
    sentences.append(sentence + "。")

    reasons = [str(reason) for reason in (first.get("reasons") or [])][:3]
    if reasons:
        sentences.append("推荐理由：" + "；".join(reasons) + "。")

    if first.get("entry_precision") == "center_fallback":
        sentences.append("该钓位缺少入口坐标，端点精度较低，出发前请核对导航终点。")

    sentences.append("车程为基线估计，请以实时导航为准，并遵守当地禁钓规定。")
    return sentences


def _format_windows(windows: Any) -> str:
    labels: list[str] = []
    for item in windows or []:
        if not isinstance(item, dict):
            continue
        label = f"{item.get('start', '?')}–{item.get('end', '?')}"
        if item.get("label"):
            label += f"（{item['label']}）"
        labels.append(label)
    return "、".join(labels)


def _alert_messages(alerts: Any) -> list[str]:
    messages: list[str] = []
    for alert in alerts or []:
        if not isinstance(alert, dict):
            continue
        if (alert.get("forced") or alert.get("level") in ("danger", "warning")) and alert.get(
            "message"
        ):
            messages.append(str(alert["message"]))
    return messages
