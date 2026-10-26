"""Bing-backed species provider (Phase 1).

Looks up community species by querying Bing with a short, spot-specific query
and matching species names from the returned titles+snippets against the shared
whitelist. No page-body fetching, no LLM, no cookies: only the public Bing
result page is parsed.

Phase 1 deliberately trades recall for simplicity and compliance. When Bing
returns no usable mentions (rate limit, captcha, ambiguous name), the spot
gets an empty list so the UI shows "暂无相关鱼种推荐" — the caller never sees
a 5xx.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

import httpx

from fishagent.core.species import KNOWN_SPECIES, SPECIES_ALIASES, normalize_species
from fishagent.schemas import SpotSpeciesQuery

logger = logging.getLogger(__name__)

# cn.bing ignores the site: operator for xiaohongshu and is noise-prone on long
# multi-term queries; two-term "{name} 钓鱼" queries gave the best signal in PoC.
_QUERY_TEMPLATE = "{name} 钓鱼"
_MAX_RESULTS = 8
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_RESULT_BLOCK_RE = re.compile(r'<li class="b_algo".*?</li>', re.DOTALL)
_TITLE_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.DOTALL)
_SNIPPET_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# Pre-built alternation of every species name and alias. Aliases are matched
# as substrings (e.g. "胖头鱼" -> "鲢鳙") to mirror the existing normaliser.
_SPECIES_PATTERNS = [(re.compile(re.escape(alias)), species) for alias, species in SPECIES_ALIASES]
_CAPTCHA_MARKERS = ("百度安全验证", "wappass.baidu.com")


class BingSpeciesProvider:
    name = "bing"
    source_key = "bing"
    source_label = "Bing 搜索"
    found_note = "来自 Bing 搜索结果，仅供参考"
    source_disclosure = (
        "鱼种信息来自公开搜索结果，仅供参考，不承诺渔获；请出发前自行核实。"
    )

    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        max_results: int = _MAX_RESULTS,
        base_url: str = "https://cn.bing.com/search",
    ) -> None:
        self._timeout = timeout_seconds
        self._max_results = max_results
        self._base_url = base_url

    async def find_species(
        self,
        spots: list[SpotSpeciesQuery],
    ) -> list[list[str]]:
        # Bing is queried sequentially per batch. The species endpoint already
        # caps batches at 10 and wraps the whole call in asyncio.wait_for, so a
        # bounded sequential loop keeps both load and failure modes simple.
        results: list[list[str]] = []
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            for spot in spots:
                results.append(await self._lookup_one(client, spot))
        return results

    async def _lookup_one(self, client: httpx.AsyncClient, spot: SpotSpeciesQuery) -> list[str]:
        name = spot.name.strip()
        if not name:
            return []
        query = _QUERY_TEMPLATE.format(name=name)
        url = f"{self._base_url}?q={quote(query)}&ensearch=0"
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("bing species query failed for %r: %s", name, exc)
            return []
        if response.status_code != 200:
            logger.warning("bing species non-200 for %r: %s", name, response.status_code)
            return []
        if any(marker in response.text for marker in _CAPTCHA_MARKERS):
            logger.warning("bing species captcha hit for %r", name)
            return []
        snippets = self._extract_snippets(response.text)
        raw = self._match_species(snippets)
        return normalize_species(raw)

    def _extract_snippets(self, html: str) -> list[str]:
        texts: list[str] = []
        for block in _RESULT_BLOCK_RE.findall(html)[: self._max_results]:
            for regex in (_TITLE_RE, _SNIPPET_RE):
                match = regex.search(block)
                if match:
                    texts.append(" ".join(_TAG_RE.sub(" ", match.group(1)).split()))
        return texts

    def _match_species(self, texts: list[str]) -> list[str]:
        # Canonical names are matched whole; aliases as substrings. This mirrors
        # core.species._canonical so the downstream normaliser can dedupe.
        hits: list[str] = []
        seen: set[str] = set()
        for text in texts:
            lowered = text.lower()
            for species in KNOWN_SPECIES:
                if species in text and species not in seen:
                    seen.add(species)
                    hits.append(species)
            for pattern, species in _SPECIES_PATTERNS:
                if pattern.search(lowered) and species not in seen:
                    seen.add(species)
                    hits.append(species)
        return hits
