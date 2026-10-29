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
import time
from urllib.parse import quote

import httpx

from fishagent.core.species import KNOWN_SPECIES, SPECIES_ALIASES, normalize_species
from fishagent.providers.safe_fetch import fetch_text
from fishagent.providers.species_extract import SpeciesExtractor
from fishagent.schemas import SpotSpeciesQuery

logger = logging.getLogger(__name__)

# Query the place name ALONE, never "{name} 钓鱼".
#
# Measured 2026-10-29: as soon as a second Chinese term is appended, cn.bing
# stops matching the water body and falls back to a dictionary entry for the
# first character — "三岔湖 钓鱼" returns 三（拼音：sān）是汉语一级通用汉字,
# and so do 三岔湖 鱼 / 渔获 / 钓鱼攻略 / "三岔湖 钓鱼" / 三岔湖 钓鱼 -汉字.
# The bare name returns the actual 景区 page, the lake's own site and local
# articles, and the pages behind them do mention species. The old template put
# every single query on the one path that is guaranteed to return nothing.
_QUERY_TEMPLATE = "{name}"
# Bing's degradation is identifiable, so it can be logged as a specific cause
# instead of looking like "this lake has no fish".
#
# Judged from the result TITLES, not the snippets. Measured 2026-10-29: on a
# degraded query 8 of 10 headlines are dictionary entries ("三（汉语汉字）_百度
# 百科", "3（阿拉伯数字之一）_百度百科"), consistently across repeats, while a
# healthy query has none. The snippet paragraphs carried only 2-4 of 16 and
# varied between requests, which is too noisy to threshold on.
_DEGRADED_MARKERS = (
    "汉语汉字",
    "阿拉伯数字",
    "汉典",
    "汉语国学",
    "新华字典",
    "维基词典",
    "字典",
)
_MAX_RESULTS = 8
# Phase 2 budget: page fetches and LLM calls are the expensive part, so they are
# capped per request rather than per spot. Fetches are concurrent, so allowing
# more pages per request costs latency only for the slowest page, and a spot
# usually needs 2-3 pages before one of them names a species.
_MAX_PAGE_FETCHES = 12
# Each LLM call is sequential and costs ~1s, so the budget is bounded by the
# endpoint timeout (4s) minus search and page-fetch time. Two calls keep the
# worst case inside the window; the per-page whitelist pass still runs on all
# fetched pages, so less LLM coverage costs little recall.
_MAX_LLM_CALLS = 2
_MAX_PAGE_CHARS_FOR_LLM = 4000
# Two snippet hits already fill a typical card; no need to spend pages on it.
_SNIPPET_SUFFICIENT_HITS = 2
# The API caps a spot at 4 species, so collecting more is wasted work.
_MAX_RESULT_SPECIES = 4
_PAGE_CONCURRENCY = 3
# Leave this much of the timeout for serialising and writing the response after
# the deepening phase decides to stop.
_DEEPEN_RESERVE_SECONDS = 0.35
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_RESULT_BLOCK_RE = re.compile(r'<li class="b_algo".*?</li>', re.DOTALL)
_TITLE_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.DOTALL)
_SNIPPET_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_HEADLINE_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.DOTALL)
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


def _share_budget(total: int, count: int, cap: int) -> list[int]:
    """Split a per-request budget across spots, filling each to ``cap`` first.

    Depth-first rather than an even split: one fetched page is often not enough
    (the top hit is frequently a government or encyclopedia page), while a spot
    that gets ``cap`` pages usually resolves. Spreading the budget one page at a
    time across every spot left most of them one page short of a result.
    """
    shares = [0] * count
    remaining = min(total, count * cap)
    while remaining > 0:
        progressed = False
        for index in range(count):
            if remaining <= 0:
                break
            if shares[index] < cap:
                shares[index] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    return shares


class BingSpeciesProvider:
    name = "bing"
    source_key = "bing"
    source_label = "Bing 搜索"
    # It does query, so an empty result is a real answer about this water body
    # (even when the SERP degraded) and a water-type fallback is justified.
    resolves_empty = True
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
        if not spots:
            return []
        # The caller wraps this call in asyncio.wait_for(timeout_seconds). Keep a
        # margin so the phase we can still finish gracefully ends before that
        # fires: a hard cancel discards *every* spot's result, while running out
        # of budget only leaves the remaining spots on their snippet hits.
        started = time.monotonic()
        results: list[list[str]] = [[] for _ in spots]
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
            # Search phase runs concurrently: each spot is an independent request
            # and nothing is shared. A 5-spot batch otherwise spends seconds
            # serially and times out the whole response at the endpoint budget.
            searches = await asyncio.gather(
                *(self._search(client, spot) for spot in spots)
            )

            pending: list[tuple[int, list[str], list[str]]] = []
            for index, found in enumerate(searches):
                if found is None:
                    continue
                hits, urls = found
                results[index] = normalize_species(hits, limit=10)
                if len(results[index]) >= _SNIPPET_SUFFICIENT_HITS:
                    continue
                pending.append((index, results[index], urls))

            # Page fetch and LLM run concurrently too: each spot's deepening is
            # independent, so running them in series made the last spots pay for
            # the first ones' latency and lose their window. Budgets are split up
            # front so the per-request caps still hold: every spot gets at least
            # one page, and at most _MAX_LLM_CALLS spots get a model call.
            if pending:
                fetch_shares = _share_budget(fetch_budget, len(pending), _PAGE_CONCURRENCY)
                llm_shares = _share_budget(llm_budget, len(pending), 1)
                deadline = started + self._timeout - _DEEPEN_RESERVE_SECONDS
                deepened = await asyncio.gather(
                    *(
                        self._deepen(client, hits, urls, fetches, llms, deadline)
                        for (_, hits, urls), fetches, llms in zip(
                            pending, fetch_shares, llm_shares
                        )
                    )
                )
                for (index, _, _), (species, _, _) in zip(pending, deepened):
                    results[index] = species
        return results

    async def _search(
        self, client: httpx.AsyncClient, spot: SpotSpeciesQuery
    ) -> tuple[list[str], list[str]] | None:
        """Run the SERP query and match species from titles/snippets.

        Returns ``(hits, candidate_urls)``, or None when the spot has no usable
        name or the search failed. Failures degrade to "no recommendation" and
        never raise.
        """
        name = spot.name.strip()
        if not name:
            return None
        query = _QUERY_TEMPLATE.format(name=name)
        url = f"{self._base_url}?q={quote(query)}&ensearch=0"
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("bing species query failed for %r: %s", name, exc)
            return None
        if response.status_code != 200:
            logger.warning("bing species non-200 for %r: %s", name, response.status_code)
            return None
        if any(marker in response.text for marker in _CAPTCHA_MARKERS):
            logger.warning("bing species captcha hit for %r", name)
            return None

        snippets = self._extract_snippets(response.text)
        if self._looks_degraded(self._extract_headlines(response.text)):
            # Logged as its own cause: this is Bing failing to match the place
            # name, not a water body without any fish. Without the distinction
            # an outage is indistinguishable from a real empty result.
            logger.warning(
                "bing returned dictionary entries instead of results for %r "
                "(degraded SERP); the place name was not matched",
                name,
            )
            return [], []

        hits = self._match_species(snippets)
        return hits, self._extract_result_urls(response.text)

    def _extract_headlines(self, html: str) -> list[str]:
        """Result titles; used to spot the dictionary fallback page."""
        return [
            " ".join(_TAG_RE.sub(" ", raw).split())
            for raw in _HEADLINE_RE.findall(html)[: self._max_results + 2]
        ]

    def _looks_degraded(self, headlines: list[str]) -> bool:
        """Detect Bing's dictionary fallback page from the result titles.

        Bing stops matching the place name and answers with single-character
        dictionary entries for its first character. On a degraded query most
        headlines are dictionary entries; on a healthy one none are. Half the
        headlines is a wide margin either way.
        """
        if not headlines:
            return False
        marked = sum(
            1
            for text in headlines
            if any(marker in text for marker in _DEGRADED_MARKERS)
        )
        return marked >= 2 and marked * 2 >= len(headlines)

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
        found = await self._search(client, spot)
        if found is None:
            return [], 0, 0
        hits, urls = found
        result = normalize_species(hits, limit=10)
        return await self._deepen(client, result, urls, fetch_budget, llm_budget)

    async def _deepen(
        self,
        client: httpx.AsyncClient,
        result: list[str],
        urls: list[str],
        fetch_budget: int,
        llm_budget: int,
        deadline: float | None = None,
    ) -> tuple[list[str], int, int]:
        """Phase 2: fetch result pages and extract species the snippets missed.

        Returns (species, page_fetches_used, llm_calls_used). ``deadline`` is a
        monotonic timestamp; once passed, remaining work is abandoned so the
        caller keeps whatever it already found instead of losing everything to
        the caller's own timeout.
        """
        # Only spend the page budget when the snippets came up short. Page text
        # is useful even without an LLM (whitelist matching runs on it), so this
        # gate depends on fetch_budget alone.
        if len(result) >= _SNIPPET_SUFFICIENT_HITS or fetch_budget <= 0:
            return normalize_species(result), 0, 0

        to_fetch = urls[: min(fetch_budget, _PAGE_CONCURRENCY)]
        fetches_used = len(to_fetch)
        try:
            pages = await self._fetch_pages(client, to_fetch)
        except Exception:  # noqa: BLE001 - a failed page must never fail the lookup
            logger.warning("page fetch stage failed", exc_info=True)
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
            # Skip the LLM entirely once the page already filled a card: the call
            # costs seconds and cannot improve a full result set.
            if len(result) + len(page_hits) >= _MAX_RESULT_SPECIES:
                break
            # LLM extraction only runs for the leftovers, and only when configured.
            if self._extractor is None or llm_budget <= 0:
                continue
            if deadline is not None and time.monotonic() >= deadline:
                # A call started now would outlive the request and its result
                # would be thrown away; stop and keep what we have.
                break
            llm_budget -= 1
            llm_calls += 1
            try:
                if deadline is None:
                    extracted = await self._extractor.extract(text[:_MAX_PAGE_CHARS_FOR_LLM])
                else:
                    # Cap the single call at the time left, so a slow model cannot
                    # push us past the deadline and cost every other spot's hits.
                    remaining = max(0.0, deadline - time.monotonic())
                    extracted = await asyncio.wait_for(
                        self._extractor.extract(text[:_MAX_PAGE_CHARS_FOR_LLM]),
                        timeout=remaining,
                    )
            except TimeoutError:
                logger.info("species LLM extraction hit the request deadline")
                break
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

