"""Bing-backed species provider.

Phase 1: query cn.bing and match species names from result titles/snippets.
Phase 2 (opt-in): additionally fetch the top result pages and let the configured
LLM extract species that the snippets did not mention.

Every stage degrades to "no recommendation" instead of raising: when Bing is
rate-limited, a page is unreachable, or no LLM key is configured, the spot gets
an empty list and the caller never sees a 5xx.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx

from fishagent.core.species import KNOWN_SPECIES, SPECIES_ALIASES, normalize_species
from fishagent.providers.safe_fetch import fetch_text
from fishagent.providers.species_extract import SpeciesExtractor
from fishagent.schemas import SpotSpeciesQuery

logger = logging.getLogger(__name__)

# cn.bing ignores the site: operator for xiaohongshu and is noise-prone on long
# multi-term queries; two-term "{name} 钓鱼" queries gave the best signal in PoC.
_QUERY_TEMPLATE = "{name} 钓鱼"
_MAX_RESULTS = 8
# Phase 2 budget: page fetches and LLM calls are the expensive part, so they are
# capped per request rather than per spot.
_MAX_PAGE_FETCHES = 6
_MAX_LLM_CALLS = 4
_MAX_PAGE_CHARS_FOR_LLM = 4000
# Two snippet hits already fill a typical card; no need to spend pages on it.
_SNIPPET_SUFFICIENT_HITS = 2
_PAGE_CONCURRENCY = 3
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_RESULT_BLOCK_RE = re.compile(r'<li class="b_algo".*?</li>', re.DOTALL)
_TITLE_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.DOTALL)
_SNIPPET_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_HREF_RE = re.compile(r'<a[^>]*href="(https?://[^"]+)"', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# Pre-built alternation of every species name and alias. Aliases are matched
# as substrings (e.g. "胖头鱼" -> "鲢鳙") to mirror the existing normaliser.
_SPECIES_PATTERNS = [(re.compile(re.escape(alias)), species) for alias, species in SPECIES_ALIASES]
_CAPTCHA_MARKERS = ("百度安全验证", "wappass.baidu.com")
# Search-engine and encyclopedia hosts rarely describe a specific water body's
# fish; skipping them saves the per-request page budget.
_SKIP_HOSTS = (
    "baike.baidu.com",
    "zhidao.baidu.com",
    "map.baidu.com",
    "bing.com",
    "microsoft.com",
    "qidian.com",
    "qq.com",
)


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
        extractor: SpeciesExtractor | None = None,
        enable_page_fetch: bool = True,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_results = max_results
        self._base_url = base_url
        self._extractor = extractor
        self._enable_page_fetch = enable_page_fetch

    async def find_species(
        self,
        spots: list[SpotSpeciesQuery],
    ) -> list[list[str]]:
        # Bing is queried sequentially per batch. The species endpoint already
        # caps batches at 10 and wraps the whole call in asyncio.wait_for, so a
        # bounded sequential loop keeps both load and failure modes simple.
        results: list[list[str]] = []
        fetch_budget = _MAX_PAGE_FETCHES if self._enable_page_fetch else 0
        llm_budget = _MAX_LLM_CALLS if self._extractor is not None else 0
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            for spot in spots:
                species, fetch_used, llm_used = await self._lookup_with_budget(
                    client, spot, fetch_budget, llm_budget
                )
                fetch_budget -= fetch_used
                llm_budget -= llm_used
                results.append(species)
        return results

    async def _lookup_one(self, client: httpx.AsyncClient, spot: SpotSpeciesQuery) -> list[str]:
        """Single-spot lookup with a full budget; convenience wrapper for tests."""
        species, _, _ = await self._lookup_with_budget(
            client, spot, _MAX_PAGE_FETCHES, _MAX_LLM_CALLS
        )
        return species

    async def _lookup_with_budget(
        self,
        client: httpx.AsyncClient,
        spot: SpotSpeciesQuery,
        fetch_budget: int = _MAX_PAGE_FETCHES,
        llm_budget: int = _MAX_LLM_CALLS,
    ) -> tuple[list[str], int, int]:
        """Return (species, page_fetches_used, llm_calls_used)."""
        name = spot.name.strip()
        if not name:
            return [], 0, 0
        query = _QUERY_TEMPLATE.format(name=name)
        url = f"{self._base_url}?q={quote(query)}&ensearch=0"
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("bing species query failed for %r: %s", name, exc)
            return [], 0, 0
        if response.status_code != 200:
            logger.warning("bing species non-200 for %r: %s", name, response.status_code)
            return [], 0, 0
        if any(marker in response.text for marker in _CAPTCHA_MARKERS):
            logger.warning("bing species captcha hit for %r", name)
            return [], 0, 0

        snippets = self._extract_snippets(response.text)
        hits = self._match_species(snippets)
        result = normalize_species(hits, limit=10)

        # Phase 2: only spend the page budget when the snippets came up short.
        # Page text is useful even without an LLM (whitelist matching runs on it),
        # so this gate depends on fetch_budget alone.
        if len(result) >= _SNIPPET_SUFFICIENT_HITS or fetch_budget <= 0:
            return normalize_species(result), 0, 0

        urls = self._extract_result_urls(response.text)
        to_fetch = urls[: min(fetch_budget, _PAGE_CONCURRENCY)]
        fetches_used = len(to_fetch)
        try:
            pages = await self._fetch_pages(client, to_fetch)
        except Exception:  # noqa: BLE001 - a failed page must never fail the lookup
            logger.warning("page fetch stage failed for %r", name, exc_info=True)
            pages = []

        page_hits: list[str] = []
        llm_calls = 0
        for text in pages:
            if not text:
                continue
            # Whitelist matching on the body text first: cheap and needs no LLM.
            for species in self._match_species([text]):
                if species not in result and species not in page_hits:
                    page_hits.append(species)
            # LLM extraction only runs for the leftovers, and only when configured.
            if self._extractor is None or llm_budget <= 0:
                continue
            llm_budget -= 1
            llm_calls += 1
            extracted = await self._extractor.extract(text[:_MAX_PAGE_CHARS_FOR_LLM])
            for species in extracted:
                if species not in result and species not in page_hits:
                    page_hits.append(species)

        result.extend(page_hits)
        return normalize_species(result), fetches_used, llm_calls

    async def _fetch_pages(self, client: httpx.AsyncClient, urls: list[str]) -> list[str]:
        if not urls:
            return []

        async def one(target: str) -> str:
            try:
                return await fetch_text(client, target)
            except Exception:  # noqa: BLE001 - a bad page must never fail the batch
                logger.info("page fetch raised for %s", target[:120], exc_info=True)
                return ""

        return list(await asyncio.gather(*(one(url) for url in urls)))

    def _extract_snippets(self, html: str) -> list[str]:
        texts: list[str] = []
        for block in _RESULT_BLOCK_RE.findall(html)[: self._max_results]:
            for regex in (_TITLE_RE, _SNIPPET_RE):
                match = regex.search(block)
                if match:
                    texts.append(" ".join(_TAG_RE.sub(" ", match.group(1)).split()))
        return texts

    def _extract_result_urls(self, html: str) -> list[str]:
        """Collect candidate page URLs, skipping hosts that never describe a spot."""
        urls: list[str] = []
        seen: set[str] = set()
        for block in _RESULT_BLOCK_RE.findall(html)[: self._max_results]:
            for raw in _HREF_RE.findall(block):
                if raw in seen:
                    continue
                if any(host in raw for host in _SKIP_HOSTS):
                    continue
                seen.add(raw)
                urls.append(raw)
        return urls

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

