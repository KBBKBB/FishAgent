"""LLM-assisted species extraction from page text.

Bing snippets often miss the species list that lives in the page body. This
module asks the configured OpenAI-compatible model to pick species names out of
fetched text, then funnels the answer through the same whitelist so the model
can never introduce an unknown or invented species.

The extractor is strictly optional: with no API key it returns nothing and the
caller falls back to plain whitelist matching.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fishagent.core.species import KNOWN_SPECIES, normalize_species

logger = logging.getLogger(__name__)

# Keep prompts bounded: a big page adds tokens without adding species.
MAX_INPUT_CHARS = 4000

SYSTEM_PROMPT = (
    "你是钓鱼资料的信息抽取器。用户会给出一段网页文本，"
    "请找出文中明确提到的、该水域里有的淡水鱼种。"
    "只能从下面列表中选择，不得编造，不确定就不要输出："
    + "、".join(KNOWN_SPECIES)
    + "。只输出 JSON，不要解释：{\"species\":[\"鲫鱼\",\"鲤鱼\"]}。"
    "如果文中没有提到具体鱼种，返回 {\"species\":[]}。"
)

_FENCED_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class SpeciesExtractor:
    """Wraps an AsyncOpenAI client; returns [] whenever extraction is impossible."""

    def __init__(self, client: Any, model: str, *, temperature: float = 0.0) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self._model)

    async def extract(self, text: str) -> list[str]:
        if not self.enabled:
            return []
        payload = (text or "").strip()
        if not payload:
            return []
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                max_tokens=120,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": payload[:MAX_INPUT_CHARS]},
                ],
            )
        except Exception:
            logger.warning("species extraction call failed", exc_info=True)
            return []

        content = _content_of(response)
        if not content:
            return []
        return normalize_species(_parse_species(content), limit=10)


def _content_of(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return ""
    return content.strip() if isinstance(content, str) else ""


def _parse_species(content: str) -> list[str]:
    text = content.strip()
    fenced = _FENCED_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        payload = json.loads(text[start : end + 1])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get("species")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]
