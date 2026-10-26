"""Phase 2: page fetching, HTML reduction, SSRF guard and LLM extraction."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from fishagent.core.species import KNOWN_SPECIES
from fishagent.providers.safe_fetch import html_to_text, is_fetchable
from fishagent.providers.species_bing import BingSpeciesProvider
from fishagent.providers.species_extract import SpeciesExtractor, _parse_species
from fishagent.schemas import SpotSpeciesQuery


def run(coro):
    return asyncio.run(coro)


# --- HTML reduction -------------------------------------------------------


def test_html_to_text_drops_scripts_and_markup():
    html = """
    <html><head><style>.a{color:red}</style><script>var x=1;</script></head>
    <body><h1>千岛湖钓鱼</h1><p>这里<b>鲫鱼</b>很多</p><!-- comment --></body></html>
    """
    text = html_to_text(html)
    assert "千岛湖钓鱼" in text
    assert "鲫鱼" in text
    assert "var x=1" not in text
    assert "color:red" not in text
    assert "<" not in text


def test_html_to_text_decodes_entities():
    assert "鲫鱼 & 鲤鱼" in html_to_text("<p>鲫鱼 &amp; 鲤鱼</p>")
    assert html_to_text("<p>a&nbsp;b</p>") == "a b"


# --- SSRF guard -----------------------------------------------------------


def test_is_fetchable_rejects_non_http_schemes():
    assert run(is_fetchable("file:///etc/passwd")) is False
    assert run(is_fetchable("ftp://example.com/x")) is False
    assert run(is_fetchable("javascript:alert(1)")) is False


def test_is_fetchable_rejects_private_and_loopback_addresses():
    for url in (
        "http://127.0.0.1/admin",
        "http://localhost/x",
        "http://10.0.0.1/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x",
    ):
        assert run(is_fetchable(url)) is False, url


def test_is_fetchable_allows_public_ip():
    assert run(is_fetchable("http://93.184.215.14/")) is True


def test_is_fetchable_rejects_unresolvable_host():
    assert run(is_fetchable("http://this-host-does-not-exist.invalid/x")) is False


# --- fetch_text -----------------------------------------------------------


def test_fetch_text_refuses_private_targets():
    from fishagent.providers.safe_fetch import fetch_text

    def handler(request):
        return httpx.Response(200, text="secret")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_text(client, "http://127.0.0.1/secret")

    assert run(go()) == ""


def test_fetch_text_ignores_binary_content_types():
    from fishagent.providers.safe_fetch import fetch_text

    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_text(client, "http://93.184.215.14/x.png")

    assert run(go()) == ""


# --- LLM extractor --------------------------------------------------------


class _FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def _extractor(content: str):
    completions = _FakeCompletions(content)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return SpeciesExtractor(client, "test-model"), completions


def test_extractor_parses_and_filters_to_whitelist():
    extractor, _ = _extractor('{"species":["鲫鱼","鲤鱼","不存在的鱼"]}')
    result = run(extractor.extract("千岛湖里有鲫鱼和鲤鱼"))
    assert result == ["鲫鱼", "鲤鱼"]
    assert set(result) <= set(KNOWN_SPECIES)


def test_extractor_handles_fenced_json():
    extractor, _ = _extractor('```json\n{"species":["草鱼"]}\n```')
    assert run(extractor.extract("草鱼")) == ["草鱼"]


def test_extractor_returns_empty_on_malformed_json():
    extractor, _ = _extractor("not json at all")
    assert run(extractor.extract("鲫鱼")) == []


def test_extractor_returns_empty_when_client_raises():
    class Boom:
        async def create(self, **kwargs):
            raise RuntimeError("upstream down")

    extractor = SpeciesExtractor(
        SimpleNamespace(chat=SimpleNamespace(completions=Boom())), "test-model"
    )
    assert run(extractor.extract("鲫鱼")) == []


def test_extractor_disabled_without_client():
    assert SpeciesExtractor(None, "m").enabled is False
    assert run(SpeciesExtractor(None, "m").extract("鲫鱼")) == []


def test_parse_species_tolerates_string_payload():
    assert _parse_species('{"species":"鲫鱼"}') == ["鲫鱼"]


# --- Bing provider Phase 2 wiring ----------------------------------------


def _serp(urls):
    blocks = "".join(
        f'<li class="b_algo"><h2><a href="{u}">钓鱼</a></h2><p>无鱼种</p></li>'
        for u in urls
    )
    return f"<html><body><ol>{blocks}</ol></body></html>"


def test_bing_extract_result_urls_skips_noisy_hosts():
    provider = BingSpeciesProvider()
    html = _serp(
        [
            "https://baike.baidu.com/item/x",
            "https://www.qidian.com/book/1",
            "https://fishweather.cn/tips/a",
            "https://www.toutiao.com/article/1",
        ]
    )
    urls = provider._extract_result_urls(html)
    assert urls == ["https://fishweather.cn/tips/a", "https://www.toutiao.com/article/1"]


def test_bing_page_fetch_disabled_keeps_phase1_behaviour():
    provider = BingSpeciesProvider(enable_page_fetch=False)
    assert provider._enable_page_fetch is False


def test_bing_does_not_use_extractor_when_snippets_already_hit():
    """Enough snippet hits means the page/LLM budget must not be spent."""

    class CountingExtractor:
        def __init__(self):
            self.calls = 0

        async def extract(self, text):
            self.calls += 1
            return ["草鱼"]

    extractor = CountingExtractor()
    provider = BingSpeciesProvider(extractor=extractor)
    # html already mentions two species in the snippet text
    html = (
        '<li class="b_algo"><h2><a href="https://example.com/a">千岛湖</a></h2>'
        "<p>鲫鱼鲤鱼很多</p></li>"
    )
    provider._extract_snippets = lambda _html: ["鲫鱼鲤鱼很多"]

    def handler(request):
        return httpx.Response(200, text=html)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider._lookup_with_budget(client, SpotSpeciesQuery(name="千岛湖"))

    species, fetches, llm_calls = run(go())
    assert set(species) >= {"鲫鱼", "鲤鱼"}
    assert fetches == 0
    assert llm_calls == 0
    assert extractor.calls == 0


def test_bing_respects_llm_budget():
    class CountingExtractor:
        def __init__(self):
            self.calls = 0

        async def extract(self, text):
            self.calls += 1
            return ["草鱼"]

    extractor = CountingExtractor()
    provider = BingSpeciesProvider(extractor=extractor)
    html = _serp(["https://example.com/a", "https://example.com/b", "https://example.com/c"])
    provider._extract_snippets = lambda _html: []

    async def fake_fetch(client, urls):
        assert len(urls) <= 3
        return ["草鱼文本" for _ in urls]

    provider._fetch_pages = fake_fetch

    def handler(request):
        return httpx.Response(200, text=html)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider._lookup_with_budget(
                client, SpotSpeciesQuery(name="千岛湖"), fetch_budget=6, llm_budget=2
            )

    species, _, llm_calls = run(go())
    assert extractor.calls == 2
    assert llm_calls == 2
    assert "草鱼" in species


def test_bing_page_text_matched_without_llm():
    """Page bodies must be whitelist-matched even when no LLM is configured."""
    provider = BingSpeciesProvider(extractor=None, enable_page_fetch=True)
    html = _serp(["https://fishweather.cn/tips/a"])
    provider._extract_snippets = lambda _html: []  # snippets yield nothing

    async def fake_fetch(client, urls):
        return ["千岛湖里鲫鱼、鲤鱼、草鱼和鲢鳙都有，偶尔能钓到青鱼"]

    provider._fetch_pages = fake_fetch

    def handler(request):
        return httpx.Response(200, text=html)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider._lookup_with_budget(client, SpotSpeciesQuery(name="千岛湖"))

    species, fetches, llm_calls = run(go())
    assert {"鲫鱼", "鲤鱼", "草鱼", "鲢鳙"} <= set(species)
    assert fetches == 1
    assert llm_calls == 0, "no extractor means no LLM calls"


def test_bing_merges_snippet_and_page_hits_without_duplicates():
    provider = BingSpeciesProvider(extractor=None, enable_page_fetch=True)
    html = _serp(["https://fishweather.cn/tips/a"])
    provider._extract_snippets = lambda _html: ["千岛湖有鲫鱼"]

    async def fake_fetch(client, urls):
        return ["同样是鲫鱼，还有鲤鱼和草鱼"]

    provider._fetch_pages = fake_fetch

    def handler(request):
        return httpx.Response(200, text=html)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider._lookup_with_budget(client, SpotSpeciesQuery(name="千岛湖"))

    species, _, _ = run(go())
    assert species.count("鲫鱼") == 1
    assert {"鲫鱼", "鲤鱼", "草鱼"} <= set(species)


def test_bing_page_fetch_failure_does_not_break_lookup():
    provider = BingSpeciesProvider()
    html = _serp(["https://example.com/a"])
    provider._extract_snippets = lambda _html: []

    async def boom(client, urls):
        raise RuntimeError("network exploded")

    provider._fetch_pages = boom

    def handler(request):
        return httpx.Response(200, text=html)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider._lookup_one(client, SpotSpeciesQuery(name="千岛湖"))

    assert run(go()) == []


@pytest.mark.parametrize(
    "budget,expected_calls",
    [(0, 0), (1, 1), (4, 4)],
)
def test_bing_llm_budget_boundaries(budget, expected_calls):
    class CountingExtractor:
        def __init__(self):
            self.calls = 0

        async def extract(self, text):
            self.calls += 1
            return []

    extractor = CountingExtractor()
    provider = BingSpeciesProvider(extractor=extractor)
    html = _serp(["https://example.com/a"])
    provider._extract_snippets = lambda _html: []

    async def fake_fetch(client, urls):
        return ["文本"] * 4

    provider._fetch_pages = fake_fetch

    def handler(request):
        return httpx.Response(200, text=html)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider._lookup_with_budget(
                client, SpotSpeciesQuery(name="千岛湖"), fetch_budget=6, llm_budget=budget
            )

    run(go())
    assert extractor.calls == expected_calls
