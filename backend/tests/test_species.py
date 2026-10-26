"""Community species recommendations: contract, mock, cache and degradation."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from conftest import PROMISE_PATTERNS, assert_iso_utc, assert_unified_error

from fishagent import deps
from fishagent.core.species import KNOWN_SPECIES
from fishagent.deps import get_species_provider
from fishagent.main import app
from fishagent.providers.species_mock import MockSpeciesProvider
from fishagent.providers.species_none import NullSpeciesProvider
from fishagent.schemas import SpotSpeciesQuery
from fishagent.services import species as species_service
from fishagent.services.species import (
    EMPTY_NOTE,
    FOUND_NOTE,
    SOURCE_DISCLOSURE,
    reset_species_cache,
)

RESULT_KEYS = {
    "spot_id",
    "spot_name",
    "species",
    "has_recommendation",
    "source",
    "source_label",
    "note",
}

MOCK_SPOTS = [
    {"spot_id": "s1", "name": "青山水库", "water_type": "水库"},
    {"spot_id": "s2", "name": "白鹭湾野塘", "water_type": "野塘"},
    {"spot_id": "s3", "name": "环城河湾", "water_type": "河流"},
]


@pytest.fixture(autouse=True)
def clear_cache():
    reset_species_cache()
    yield
    reset_species_cache()


@pytest.fixture()
def override_provider():
    def install(provider):
        app.dependency_overrides[get_species_provider] = lambda: provider

    yield install
    app.dependency_overrides.pop(get_species_provider, None)


def request_species(client, spots):
    return client.post("/api/spots/species", json={"spots": spots})


def test_batch_contract_and_input_order(client):
    response = request_species(client, MOCK_SPOTS)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["provider"] == "mock"
    assert payload["degraded"] is False
    assert payload["source_disclosure"] == SOURCE_DISCLOSURE
    assert_iso_utc(payload["generated_at"])
    assert len(payload["results"]) == len(MOCK_SPOTS)
    assert [item["spot_name"] for item in payload["results"]] == [
        spot["name"] for spot in MOCK_SPOTS
    ]
    assert [item["spot_id"] for item in payload["results"]] == ["s1", "s2", "s3"]

    for item in payload["results"]:
        assert set(item) == RESULT_KEYS
        assert isinstance(item["has_recommendation"], bool)
        assert isinstance(item["species"], list)
        assert item["source"] in ("xiaohongshu", "none")
        assert set(item["species"]) <= set(KNOWN_SPECIES)
        if item["has_recommendation"]:
            assert item["species"]
            assert item["source"] == "xiaohongshu"
            assert item["source_label"]
            assert item["note"] == FOUND_NOTE
        else:
            assert item["species"] == []
            assert item["source"] == "none"
            assert item["source_label"] == ""
            assert item["note"] == EMPTY_NOTE


def test_duplicate_queries_return_one_result_each(client):
    spots = [MOCK_SPOTS[0], MOCK_SPOTS[1], MOCK_SPOTS[0]]
    response = request_species(client, spots)
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    assert results[0] == results[2]


def test_mock_provider_covers_both_outcomes():
    provider = MockSpeciesProvider()
    spots = [
        SpotSpeciesQuery(name=f"示例水域{i}", water_type="河流") for i in range(50)
    ]
    results = asyncio.run(provider.find_species(spots))
    assert any(results), "Mock 应至少产生一个鱼种推荐"
    assert any(not item for item in results), "Mock 应至少产生一个无推荐场景"


def test_unrecognised_and_alias_species_are_normalised(client, override_provider):
    class FakeProvider:
        name = "test"
        source_label = "小红书（测试）"

        async def find_species(self, spots):
            return [["草鱼", "不存在的鱼", "草鱼", "胖头鱼"]] * len(spots)

    override_provider(FakeProvider())
    response = request_species(client, [MOCK_SPOTS[0]])
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["species"] == ["草鱼", "鲢鳙"]
    assert item["has_recommendation"] is True


def test_null_provider_reports_no_recommendation(client, override_provider):
    override_provider(NullSpeciesProvider())
    response = request_species(client, MOCK_SPOTS[:2])
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "none"
    assert payload["degraded"] is False
    for item in payload["results"]:
        assert item["species"] == []
        assert item["has_recommendation"] is False
        assert item["note"] == EMPTY_NOTE


def test_provider_failure_degrades_without_failing_request(client, override_provider):
    class FailingProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            raise RuntimeError("community lookup unavailable")

    override_provider(FailingProvider())
    response = request_species(client, MOCK_SPOTS)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["degraded"] is True
    assert len(payload["results"]) == len(MOCK_SPOTS)
    for item in payload["results"]:
        assert item["species"] == []
        assert item["has_recommendation"] is False
        assert item["note"] == EMPTY_NOTE


def test_provider_timeout_degrades_without_failing_request(client, override_provider):
    class TimeoutProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            raise asyncio.TimeoutError

    override_provider(TimeoutProvider())
    response = request_species(client, MOCK_SPOTS[:1])
    assert response.status_code == 200, response.text
    assert response.json()["degraded"] is True
    assert response.json()["results"][0]["note"] == EMPTY_NOTE


def test_cache_prevents_duplicate_provider_calls(client, override_provider):
    class CountingProvider:
        name = "test"
        source_label = "小红书（测试）"

        def __init__(self):
            self.calls = 0

        async def find_species(self, spots):
            self.calls += 1
            return [["鲫鱼"] for _ in spots]

    provider = CountingProvider()
    override_provider(provider)

    first = request_species(client, MOCK_SPOTS)
    second = request_species(client, MOCK_SPOTS)
    assert first.status_code == second.status_code == 200
    assert provider.calls == 1
    assert first.json()["results"] == second.json()["results"]


def test_validation_rejects_blank_and_oversized_batches(client):
    blank = request_species(client, [{"name": "   "}])
    assert_unified_error(blank, 422, "VALIDATION_ERROR")

    empty = client.post("/api/spots/species", json={"spots": []})
    assert_unified_error(empty, 422, "VALIDATION_ERROR")

    too_many = request_species(
        client,
        [{"name": f"水域{i}", "water_type": "河流"} for i in range(11)],
    )
    assert_unified_error(too_many, 422, "VALIDATION_ERROR")


def test_species_response_has_no_catch_promises(client):
    response = request_species(client, MOCK_SPOTS)
    assert response.status_code == 200
    serialized = response.text
    for pattern in PROMISE_PATTERNS:
        assert pattern not in serialized, f"鱼种响应含承诺性表述：{pattern}"
    assert "小红书" in response.json()["source_disclosure"]


# ---------------------------------------------------------------------------
# 第二轮补测：降级语义、缓存隔离/TTL/键归一化、边界、provider 选择与超时。
# ---------------------------------------------------------------------------


def assert_all_empty_degraded(payload, expected_count):
    """契约 4.6：降级响应必须 200 + 全空 + degraded=true，且不泄露缓存值。"""
    assert payload["degraded"] is True
    assert len(payload["results"]) == expected_count
    for item in payload["results"]:
        assert item["species"] == []
        assert item["has_recommendation"] is False
        assert item["source"] == "none"
        assert item["source_label"] == ""
        assert item["note"] == EMPTY_NOTE


@pytest.mark.parametrize(
    "payload",
    [
        {"rows": []},
        "鲫鱼",
        None,
        [],
        [["鲫鱼"], ["鲤鱼"]],
        [None],
        ["鲫鱼"],
    ],
    ids=["dict", "str", "none", "no-rows", "extra-rows", "null-row", "str-row"],
)
def test_malformed_provider_payload_degrades(client, override_provider, payload):
    """契约 4.6：外层非 list / 行数不符 / 单行非 list 均降级为 200 全空。"""

    class BrokenProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            return payload

    override_provider(BrokenProvider())
    response = request_species(client, [MOCK_SPOTS[0]])
    assert response.status_code == 200, response.text
    assert_all_empty_degraded(response.json(), 1)


def test_degradation_does_not_mix_cached_positive(client, override_provider):
    """契约 4.6：已有正向缓存时 provider 失败，整批必须全空，不得混入缓存。"""

    class HealthyProvider:
        name = "test"
        source_label = "小红书（测试）"

        async def find_species(self, spots):
            return [["鲫鱼"] for _ in spots]

    override_provider(HealthyProvider())
    first = request_species(client, [{"name": "隔离水域"}])
    assert first.status_code == 200
    assert first.json()["degraded"] is False
    assert first.json()["results"][0]["species"] == ["鲫鱼"]

    class FailingProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            raise RuntimeError("community lookup unavailable")

    override_provider(FailingProvider())
    second = request_species(client, [{"name": "隔离水域"}, {"name": "隔离新水域"}])
    assert second.status_code == 200, second.text
    assert_all_empty_degraded(second.json(), 2)
    assert "鲫鱼" not in second.text


def test_negative_cache_ttl_and_reuse(client, override_provider):
    """契约 4.6：降级负缓存最多 5 分钟，窗口内不得再次请求 provider。"""

    class FailingProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            raise RuntimeError("boom")

    override_provider(FailingProvider())
    response = request_species(client, [{"name": "负缓存水域"}])
    assert response.status_code == 200
    assert response.json()["degraded"] is True

    entry = species_service._cache[("负缓存水域", "")]
    remaining = entry.expires_at - time.monotonic()
    assert entry.degraded is True
    assert entry.species == []
    assert 250 <= remaining <= 300

    class HealthyProvider:
        name = "test"
        source_label = ""

        def __init__(self):
            self.calls = 0

        async def find_species(self, spots):
            self.calls += 1
            return [["鲫鱼"] for _ in spots]

    healthy = HealthyProvider()
    override_provider(healthy)
    again = request_species(client, [{"name": "负缓存水域"}])
    assert healthy.calls == 0
    assert_all_empty_degraded(again.json(), 1)


def test_positive_cache_ttl_is_full_hour_and_reused(client, override_provider):
    """契约 4.6：成功非空结果使用完整 TTL（默认 3600s）。"""

    class HealthyProvider:
        name = "test"
        source_label = "小红书（测试）"

        async def find_species(self, spots):
            return [["鲫鱼"] for _ in spots]

    override_provider(HealthyProvider())
    response = request_species(client, [{"name": "正缓存水域"}])
    assert response.status_code == 200
    assert response.json()["degraded"] is False

    entry = species_service._cache[("正缓存水域", "")]
    remaining = entry.expires_at - time.monotonic()
    assert entry.degraded is False
    assert entry.species == ["鲫鱼"]
    assert 3500 <= remaining <= 3600

    class ExplodingProvider:
        name = "test"
        source_label = ""

        def __init__(self):
            self.calls = 0

        async def find_species(self, spots):
            self.calls += 1
            raise RuntimeError("must not be called")

    exploding = ExplodingProvider()
    override_provider(exploding)
    again = request_species(client, [{"name": "正缓存水域"}])
    assert exploding.calls == 0
    assert again.json()["degraded"] is False
    assert again.json()["results"][0]["species"] == ["鲫鱼"]


def test_empty_success_cache_ttl_is_short(client, override_provider):
    """契约 4.6：空结果（provider 成功但无鱼种）同样只缓存 5 分钟。"""

    class EmptyProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            return [[] for _ in spots]

    override_provider(EmptyProvider())
    response = request_species(client, [{"name": "空结果水域"}])
    assert response.status_code == 200
    assert response.json()["degraded"] is False
    assert response.json()["results"][0]["note"] == EMPTY_NOTE

    entry = species_service._cache[("空结果水域", "")]
    remaining = entry.expires_at - time.monotonic()
    assert entry.degraded is False
    assert entry.species == []
    assert 250 <= remaining <= 300

    class HealthyProvider:
        name = "test"
        source_label = ""

        def __init__(self):
            self.calls = 0

        async def find_species(self, spots):
            self.calls += 1
            return [["鲫鱼"] for _ in spots]

    healthy = HealthyProvider()
    override_provider(healthy)
    again = request_species(client, [{"name": "空结果水域"}])
    assert healthy.calls == 0
    assert again.json()["degraded"] is False
    assert again.json()["results"][0]["species"] == []


def test_cache_keys_isolate_pipe_names(client, override_provider):
    """契约 4.6：缓存键按 (name, water_type) 元组隔离，名称含 | 不得串键。"""

    class Provider:
        name = "test"
        source_label = "小红书（测试）"

        def __init__(self):
            self.calls = 0
            self.batches = []

        async def find_species(self, spots):
            self.calls += 1
            self.batches.append([(spot.name, spot.water_type) for spot in spots])
            rows = {
                ("A|B", "河流"): ["鲫鱼"],
                ("A", "B|河流"): ["鲤鱼"],
            }
            return [rows.get((spot.name, spot.water_type), ["草鱼"]) for spot in spots]

    provider = Provider()
    override_provider(provider)
    response = request_species(
        client,
        [
            {"name": "A|B", "water_type": "河流"},
            {"name": "A", "water_type": "B|河流"},
        ],
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["species"] == ["鲫鱼"]
    assert results[1]["species"] == ["鲤鱼"]
    assert provider.calls == 1
    assert len(provider.batches[0]) == 2


def test_same_name_different_water_type_is_not_shared(client, override_provider):
    """契约 4.6：name 相同但 water_type 不同不得互相命中缓存。"""

    class Provider:
        name = "test"
        source_label = "小红书（测试）"

        def __init__(self):
            self.calls = 0

        async def find_species(self, spots):
            self.calls += 1
            return [
                ["鲫鱼"] if spot.water_type == "河流" else ["鲤鱼"]
                for spot in spots
            ]

    provider = Provider()
    override_provider(provider)
    first = request_species(client, [{"name": "同名水域", "water_type": "河流"}])
    second = request_species(client, [{"name": "同名水域", "water_type": "湖泊"}])
    assert provider.calls == 2
    assert first.json()["results"][0]["species"] == ["鲫鱼"]
    assert second.json()["results"][0]["species"] == ["鲤鱼"]


def test_whitespace_variants_share_one_cache_key(client, override_provider):
    """契约 4.6：name/water_type 前后空白归一后应命中同一缓存键。"""

    class Provider:
        name = "test"
        source_label = "小红书（测试）"

        def __init__(self):
            self.calls = 0
            self.batch_sizes = []

        async def find_species(self, spots):
            self.calls += 1
            self.batch_sizes.append(len(spots))
            return [["鲫鱼"] for _ in spots]

    provider = Provider()
    override_provider(provider)
    response = request_species(
        client,
        [
            {"name": " 空白水域 ", "water_type": " 河流 "},
            {"name": "空白水域", "water_type": "河流"},
        ],
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert provider.calls == 1
    assert provider.batch_sizes == [1]
    assert results[0] == results[1]


def test_duplicate_queries_query_provider_once_per_request(client, override_provider):
    """契约 4.6：同 name|water_type 重复项单次请求内只查询一次。"""

    class Provider:
        name = "test"
        source_label = "小红书（测试）"

        def __init__(self):
            self.calls = 0
            self.batch_sizes = []

        async def find_species(self, spots):
            self.calls += 1
            self.batch_sizes.append(len(spots))
            return [["鲫鱼"] for _ in spots]

    provider = Provider()
    override_provider(provider)
    spots = [MOCK_SPOTS[0], MOCK_SPOTS[0], MOCK_SPOTS[1], MOCK_SPOTS[0]]
    response = request_species(client, spots)
    assert response.status_code == 200
    results = response.json()["results"]
    assert provider.calls == 1
    assert provider.batch_sizes == [2]
    assert len(results) == 4
    assert results[0] == results[1] == results[3]


def test_recommendations_capped_at_four_species(client, override_provider):
    """契约 4.6：单钓位最多返回 4 个已知鱼种。"""

    class Provider:
        name = "test"
        source_label = "小红书（测试）"

        async def find_species(self, spots):
            return [["鲫鱼", "鲤鱼", "草鱼", "鲢鳙", "青鱼"] for _ in spots]

    override_provider(Provider())
    response = request_species(client, [MOCK_SPOTS[0]])
    assert response.status_code == 200
    assert response.json()["results"][0]["species"] == [
        "鲫鱼",
        "鲤鱼",
        "草鱼",
        "鲢鳙",
    ]


def test_batch_and_name_boundaries(client):
    """契约 4.6：spots 1–10、name 1–120（含端点），超限返回 422。"""
    ten = request_species(
        client,
        [{"name": f"批量水域{i}", "water_type": "河流"} for i in range(10)],
    )
    assert ten.status_code == 200, ten.text
    assert len(ten.json()["results"]) == 10

    eleven = request_species(
        client,
        [{"name": f"批量水域{i}", "water_type": "河流"} for i in range(11)],
    )
    assert_unified_error(eleven, 422, "VALIDATION_ERROR")

    longest_name = "水" * 120
    longest = request_species(client, [{"name": longest_name, "water_type": "河流"}])
    assert longest.status_code == 200, longest.text
    assert longest.json()["results"][0]["spot_name"] == longest_name

    too_long = request_species(client, [{"name": "水" * 121}])
    assert_unified_error(too_long, 422, "VALIDATION_ERROR")


def test_name_only_query_is_accepted(client):
    """契约 4.6：只有 name 时其余字段可空，响应结构完整。"""
    response = request_species(client, [{"name": "青山水库"}])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["degraded"] is False
    item = payload["results"][0]
    assert item["spot_id"] is None
    assert item["spot_name"] == "青山水库"
    assert isinstance(item["species"], list)
    assert item["has_recommendation"] == bool(item["species"])
    assert item["source"] == ("xiaohongshu" if item["species"] else "none")
    assert item["note"] == (FOUND_NOTE if item["species"] else EMPTY_NOTE)


@pytest.mark.parametrize(
    ("mock_mode", "configured", "expected"),
    [
        (True, "", MockSpeciesProvider),
        (False, "", NullSpeciesProvider),
        (True, "mock", MockSpeciesProvider),
        (False, "mock", MockSpeciesProvider),
        (True, "none", NullSpeciesProvider),
        (False, "none", NullSpeciesProvider),
        (True, "disabled", NullSpeciesProvider),
        (False, "MOCK", MockSpeciesProvider),
        (True, "xiaohongshu", NullSpeciesProvider),
    ],
    ids=[
        "mock-mode-empty",
        "real-mode-empty",
        "mock-mode-mock",
        "real-mode-mock",
        "mock-mode-none",
        "real-mode-none",
        "disabled",
        "case-insensitive",
        "unknown",
    ],
)
def test_species_provider_selection_matrix(
    monkeypatch,
    mock_mode,
    configured,
    expected,
):
    """契约 4.6：留空时 Mock 模式用 mock、真实模式用 none。"""
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: SimpleNamespace(
            mock_mode=mock_mode,
            species_provider=configured,
        ),
    )
    assert type(deps.get_species_provider()) is expected


async def test_cancelled_error_is_not_swallowed():
    """契约 4.6：CancelledError 必须向上传播，不得伪装成降级 200。"""

    class CancelledProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await species_service.build_species_recommendations(
            CancelledProvider(),
            [SpotSpeciesQuery(name="取消水域")],
        )


async def test_real_asyncio_wait_for_timeout_degrades(monkeypatch):
    """契约 4.6：真实 asyncio.wait_for 超时路径应降级，而非只依赖 provider 抛错。"""

    class SlowProvider:
        name = "test"
        source_label = ""

        def __init__(self):
            self.cancelled = False

        async def find_species(self, spots):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return [["鲫鱼"] for _ in spots]

    monkeypatch.setattr(
        species_service,
        "get_settings",
        lambda: SimpleNamespace(
            species_timeout_seconds=0.01,
            species_cache_ttl_seconds=3600,
        ),
    )
    provider = SlowProvider()
    response = await species_service.build_species_recommendations(
        provider,
        [SpotSpeciesQuery(name="超时水域")],
    )
    assert response.degraded is True
    assert provider.cancelled is True
    assert response.results[0].species == []
    assert response.results[0].note == EMPTY_NOTE


async def test_mock_provider_is_deterministic_bounded_and_samples_empty():
    """契约第 5 节：Mock 以 name|water_type 为种子，1–3 种、约 1/5 空、标注 Mock。"""
    provider = MockSpeciesProvider()
    assert "Mock" in provider.source_label

    spots = [
        SpotSpeciesQuery(name=f"抽样水域{i}", water_type="河流") for i in range(200)
    ]
    first = await provider.find_species(spots)
    second = await MockSpeciesProvider().find_species(spots)
    assert first == second, "Mock 结果必须确定可复现"

    empties = sum(1 for row in first if not row)
    assert 0 < empties < len(spots)
    assert 0.10 <= empties / len(spots) <= 0.30

    for row in first:
        assert len(row) <= 3
        assert set(row) <= set(KNOWN_SPECIES)
        assert len(set(row)) == len(row), "Mock 行内鱼种不得重复"
        if row:
            assert 1 <= len(row) <= 3


def _bing_html(snippets):
    """Build a minimal Bing SERP with one result block per (title, snippet)."""
    blocks = "".join(
        f'<li class="b_algo"><h2><a href="https://example.com/{i}">{title}</a></h2><p>{snippet}</p></li>'
        for i, (title, snippet) in enumerate(snippets)
    )
    return f"<html><body><ol>{blocks}</ol></body></html>"


def test_bing_provider_matches_species_from_snippets():
    from fishagent.providers.species_bing import BingSpeciesProvider

    snippets = [
        ("千岛湖钓鱼攻略", "本水域盛产鲢鳙、鲫鱼和鲤鱼，野钓效果不错"),
        ("千岛湖鱼情", "主钓翘嘴与马口，偶尔上鲤鱼"),
    ]
    provider = BingSpeciesProvider(timeout_seconds=5.0)

    raw = provider._match_species(provider._extract_snippets(_bing_html(snippets)))

    # Aliases and canonical names both resolve through normalize_species.
    from fishagent.core.species import normalize_species

    # limit=10 here: the default cap of 4 belongs to the API layer, and this
    # test checks the matcher, not the truncation.
    result = normalize_species(raw, limit=10)
    assert set(result) <= set(KNOWN_SPECIES)
    assert "鲢鳙" in result and "鲫鱼" in result and "鲤鱼" in result
    assert "翘嘴" in result and "马口" in result
    assert len(result) == len(set(result))


def test_bing_provider_returns_empty_when_no_species_mentioned():
    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider(timeout_seconds=5.0)
    html = _bing_html([("青山小说", "一部修仙小说，与钓鱼无关")])
    assert provider._match_species(provider._extract_snippets(html)) == []


def test_bing_provider_uses_http_client(monkeypatch):
    import httpx

    from fishagent.providers.species_bing import BingSpeciesProvider

    captured = {"url": None}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            text=_bing_html(
                [("千岛湖钓鱼", "这里鲫鱼、鲤鱼很多，偶尔能钓到鲢鳙")]
            ),
        )

    transport = httpx.MockTransport(handler)
    provider = BingSpeciesProvider(timeout_seconds=5.0)

    # Inject the mock transport by creating the client ourselves and calling
    # the private lookup so the test does not hit the real network.
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider._lookup_one(client, SpotSpeciesQuery(name="千岛湖"))

    result = asyncio.run(run())
    assert captured["url"].startswith("https://cn.bing.com/search?q=")
    # The query is percent-encoded on the wire.
    assert "%E5%8D%83%E5%B2%9B%E6%B9%96" in captured["url"]  # 千岛湖
    assert set(result) <= set(KNOWN_SPECIES)
    assert {"鲫鱼", "鲤鱼", "鲢鳙"} <= set(result)


def test_bing_provider_returns_empty_on_captcha(monkeypatch):
    import httpx

    from fishagent.providers.species_bing import BingSpeciesProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>百度安全验证 wappass.baidu.com</html>")

    transport = httpx.MockTransport(handler)
    provider = BingSpeciesProvider(timeout_seconds=5.0)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider._lookup_one(client, SpotSpeciesQuery(name="任何水域"))

    assert asyncio.run(run()) == []


def test_bing_provider_returns_empty_on_non_200(monkeypatch):
    import httpx

    from fishagent.providers.species_bing import BingSpeciesProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="")

    transport = httpx.MockTransport(handler)
    provider = BingSpeciesProvider(timeout_seconds=5.0)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider._lookup_one(client, SpotSpeciesQuery(name="任何水域"))

    assert asyncio.run(run()) == []


def test_bing_provider_returns_empty_on_network_error(monkeypatch):
    import httpx

    from fishagent.providers.species_bing import BingSpeciesProvider

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    transport = httpx.MockTransport(handler)
    provider = BingSpeciesProvider(timeout_seconds=5.0)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider._lookup_one(client, SpotSpeciesQuery(name="任何水域"))

    assert asyncio.run(run()) == []


def test_bing_provider_skips_blank_name():
    import httpx

    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider(timeout_seconds=5.0)

    # SpotSpeciesQuery rejects a blank name, so build a stand-in that only
    # exposes the field the provider reads.
    blank = SimpleNamespace(name="   ")

    async def run():
        async with httpx.AsyncClient() as client:
            return await provider._lookup_one(client, blank)

    assert asyncio.run(run()) == []


def test_bing_provider_respects_max_results():
    from fishagent.providers.species_bing import BingSpeciesProvider

    snippets = [("水域", "鲫鱼")] * 20
    provider = BingSpeciesProvider(timeout_seconds=5.0, max_results=3)
    snippets_out = provider._extract_snippets(_bing_html(snippets))
    # 2 texts per block (title + snippet), 3 blocks max -> 6 texts.
    assert len(snippets_out) == 6


def test_bing_provider_declares_its_own_disclosure():
    """The Bing adapter must not reuse Xiaohongshu wording in its response."""
    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider()
    assert provider.source_key == "bing"
    assert "Bing" in provider.source_label
    assert "小红书" not in provider.found_note
    assert "小红书" not in provider.source_disclosure
    assert "仅供参考" in provider.found_note
    assert "仅供参考" in provider.source_disclosure


def test_service_uses_provider_specific_source_metadata(client, override_provider):
    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider()

    async def fake_find_species(spots):
        return [["鲫鱼"] for _ in spots]

    provider.find_species = fake_find_species  # type: ignore[method-assign]
    override_provider(provider)

    payload = request_species(client, [{"spot_id": "p1", "name": "千岛湖"}]).json()
    item = payload["results"][0]

    assert item["source"] == "bing"
    assert item["source_label"] == provider.source_label
    assert item["note"] == provider.found_note
    assert payload["source_disclosure"] == provider.source_disclosure
    assert payload["provider"] == "bing"


def test_species_provider_selection_includes_bing():
    import fishagent.deps as deps_mod
    from fishagent.config import Settings
    from fishagent.providers.species_bing import BingSpeciesProvider

    original = deps_mod.get_settings
    settings = Settings(species_provider="bing", mock_mode=False)
    try:
        deps_mod.get_settings = lambda: settings
        provider = deps_mod.get_species_provider()
        assert isinstance(provider, BingSpeciesProvider)
    finally:
        deps_mod.get_settings = original
