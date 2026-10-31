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
    TYPICAL_NOTE,
    TYPICAL_SOURCE_LABEL,
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
    # Derived from `species` in the same response, so a card cannot show bait
    # for a fish its own species line does not list.
    "baits",
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
        assert item["source"] in ("xiaohongshu", "typical", "none")
        assert set(item["species"]) <= set(KNOWN_SPECIES)
        if item["has_recommendation"] and item["source"] == "xiaohongshu":
            assert item["species"]
            assert item["source_label"]
            assert item["note"] == FOUND_NOTE
        elif item["has_recommendation"]:
            # 同水域类型的参考值：不是引用来源，文案必须说清楚。
            assert item["source"] == "typical"
            assert item["species"]
            assert item["source_label"] == TYPICAL_SOURCE_LABEL
            assert item["note"] == TYPICAL_NOTE
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


# --- 同一水域类型的参考值（无引用来源时的保底）-------------------------------


class _EmptyAnswerProvider:
    """Looks up, finds nothing: this is "not found", unlike the null provider."""

    name = "bing"
    source_key = "bing"
    source_label = "Bing 搜索"
    found_note = "来自 Bing 搜索结果，仅供参考"
    source_disclosure = "鱼种信息来自公开搜索结果，仅供参考。"
    resolves_empty = True

    async def find_species(self, spots):
        return [[] for _ in spots]


def test_empty_lookup_falls_back_to_the_water_type(client, override_provider):
    """A real lookup that found nothing still gives the user something usable."""
    override_provider(_EmptyAnswerProvider())
    payload = request_species(
        client, [{"spot_id": "s1", "name": "某个没查到的水库", "water_type": "水库"}]
    ).json()
    item = payload["results"][0]

    assert item["species"], "should offer the water-type species"
    assert item["has_recommendation"] is True
    assert item["source"] == "typical"
    assert item["source_label"] == TYPICAL_SOURCE_LABEL
    assert item["note"] == TYPICAL_NOTE
    assert set(item["species"]) <= set(KNOWN_SPECIES)


def test_typical_value_is_labelled_as_not_about_this_lake(client, override_provider):
    """The wording must not let a water-type guess pass as a report."""
    override_provider(_EmptyAnswerProvider())
    payload = request_species(
        client, [{"spot_id": "s1", "name": "某湖", "water_type": "湖泊"}]
    ).json()
    note = payload["results"][0]["note"]

    assert "未查到该水域" in note
    assert "同类水域" in note
    # Never claim it is a community or search report.
    assert "网友" not in note
    assert "搜索" not in note


def test_disabled_provider_does_not_invent_species(client, override_provider):
    """NullSpeciesProvider means "switched off", not "nothing found".

    Regression: without this distinction every spot whose species lookup was
    disabled would show a plausible-looking list, claiming knowledge the
    deployment deliberately does not have.
    """
    override_provider(NullSpeciesProvider())
    payload = request_species(
        client, [{"spot_id": "s1", "name": "某湖", "water_type": "湖泊"}]
    ).json()
    item = payload["results"][0]

    assert item["species"] == []
    assert item["has_recommendation"] is False
    assert item["source"] == "none"
    assert item["note"] == EMPTY_NOTE


def test_degraded_response_does_not_fall_back(client, override_provider):
    """Degraded means the source failed; a fallback would imply we had checked."""

    class _Boom:
        name = "bing"
        source_label = "Bing 搜索"
        resolves_empty = True

        async def find_species(self, spots):
            raise RuntimeError("upstream down")

    override_provider(_Boom())
    payload = request_species(
        client, [{"spot_id": "s1", "name": "某湖", "water_type": "湖泊"}]
    ).json()

    assert payload["degraded"] is True
    assert payload["results"][0]["species"] == []
    assert payload["results"][0]["source"] == "none"


def test_unknown_water_type_gets_no_fallback(client, override_provider):
    """Guessing for an unlabelled water body would be worse than saying nothing."""
    override_provider(_EmptyAnswerProvider())
    payload = request_species(
        client, [{"spot_id": "s1", "name": "某处", "water_type": ""}]
    ).json()
    item = payload["results"][0]
    assert item["species"] == []
    assert item["source"] == "none"


@pytest.mark.parametrize(
    ("water_type", "expected"),
    [
        ("水库", "鲢鳙"),
        ("天然湖泊", "草鱼"),
        ("小型野塘", "黑鱼"),
        ("河流", "白条"),
        ("", None),
        ("冰面", None),
    ],
)
def test_typical_species_by_water_type(water_type, expected):
    from fishagent.core.species import typical_species_for

    result = typical_species_for(water_type)
    if expected is None:
        assert result == []
    else:
        assert expected in result
        assert len(result) == 4


# --- Bing 查询式与退化检测 ---------------------------------------------------


def test_bing_queries_the_place_name_alone():
    """Regression: "{name} 钓鱼" put every query on Bing's broken path.

    Measured 2026-10-29: appending any second Chinese term makes cn.bing answer
    with a single-character dictionary entry (三 sān 是汉语通用汉字) instead of
    the lake. The bare name returns the actual water body.
    """
    from fishagent.providers.species_bing import _QUERY_TEMPLATE

    assert "钓鱼" not in _QUERY_TEMPLATE
    assert "{" not in _QUERY_TEMPLATE.replace("{name}", "", 1)
    assert _QUERY_TEMPLATE.format(name="三岔湖") == "三岔湖"


def _headline_page(headlines):
    return "".join(f"<h2><a>{text}</a></h2>" for text in headlines)


def test_dictionary_fallback_page_is_detected():
    """The dictionary SERP must be recognised so the log says what happened."""
    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider()
    degraded = [
        "三（汉语汉字）_百度百科",
        "3（阿拉伯数字之一）_百度百科",
        "三 sān - 汉典",
        "三 的意思, 三 的解释 -汉语国学",
        "三 -字典-意思-解释-拼音",
        "三 怎么读_ 三 的拼音 - 新华字典",
        "三 - 维基词典，自由的多语言词典",
        "成都天气_天气预报",
        "三岔湖门票_携程",
        "成都旅游攻略",
    ]
    assert provider._looks_degraded(provider._extract_headlines(_headline_page(degraded)))


def test_healthy_results_are_not_flagged_as_degraded():
    """A real result set must never be mistaken for the fallback page."""
    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider()
    healthy = [
        "三岔湖 景区_百度百科",
        "资阳 三岔湖 景区_百度百科",
        "三岔湖 - 天府明珠 生态仙境",
        "三岔湖钓鱼攻略 - 简书",
        "成都三岔湖钓鱼，一钓就上瘾 - 哔哩哔哩",
        "简阳三岔湖钓鱼攻略及须知 - 成都本地宝",
        "请教三岔湖钓鱼位置 - 百度贴吧",
        "三岔湖水库鱼情 - 钓鱼之家",
        "四川三岔湖旅游攻略",
        "三岔湖环湖绿道",
    ]
    assert not provider._looks_degraded(provider._extract_headlines(_headline_page(healthy)))


def test_degraded_serp_yields_no_species_instead_of_noise():
    """End to end: a dictionary page must not be mined for species."""

    class _Reply:
        status_code = 200
        text = _headline_page(
            [
                "三（汉语汉字）_百度百科",
                "3（阿拉伯数字之一）_百度百科",
                "三 sān - 汉典",
                "三 -字典-意思-解释-拼音",
            ]
        )
        encoding = "utf-8"

    from fishagent.providers.species_bing import BingSpeciesProvider

    provider = BingSpeciesProvider()

    class _Client:
        async def get(self, url):
            return _Reply()

    found = asyncio.run(provider._search(_Client(), SpotSpeciesQuery(name="三岔湖")))
    assert found == ([], [])


# --- Phase 2 must fit inside the request budget -----------------------------
#
# Measured 2026-10-29 on the real serp: a single tieba.baidu.com page kept the
# page-fetch stage open for 10.9s against a 4s provider budget. The stage had no
# deadline of its own, only the per-request client timeout, so it outlived the
# caller's ``wait_for``; the cancellation then threw away the whole batch,
# including snippet hits that had already been found. From the phone that looked
# like "请求超时", while the server actually answered 200 with every spot empty.


def _deadline_provider(**kwargs):
    from fishagent.providers.species_bing import BingSpeciesProvider

    return BingSpeciesProvider(timeout_seconds=0.5, **kwargs)


def test_page_fetch_cannot_outlive_the_deadline(monkeypatch):
    """A hung page yields the snippet hits instead of cancelling the batch."""
    from fishagent.providers import species_bing

    async def hang(self, client, urls):
        await asyncio.sleep(60)
        return []

    monkeypatch.setattr(species_bing.BingSpeciesProvider, "_fetch_pages", hang)
    provider = _deadline_provider()

    class _Client:
        pass

    started = time.monotonic()
    result, fetches, calls = asyncio.run(
        provider._deepen(
            _Client(),
            ["鲫鱼"],
            ["https://example.com/a"],
            fetch_budget=3,
            llm_budget=0,
            deadline=time.monotonic() + 0.3,
        )
    )
    elapsed = time.monotonic() - started
    # The snippet hit survives; the stage does not run to the client timeout.
    assert result == ["鲫鱼"]
    assert calls == 0
    assert elapsed < 2.0, f"page fetch ignored the deadline ({elapsed:.2f}s)"


def test_deadline_already_passed_skips_fetching_entirely():
    from fishagent.providers.species_bing import BingSpeciesProvider

    called = {"n": 0}

    async def should_not_run(self, client, urls):
        called["n"] += 1
        return []

    from fishagent.providers import species_bing

    original = species_bing.BingSpeciesProvider._fetch_pages
    species_bing.BingSpeciesProvider._fetch_pages = should_not_run
    try:
        provider = BingSpeciesProvider()
        result, fetches, _ = asyncio.run(
            provider._deepen(
                object(),
                ["鲤鱼"],
                ["https://example.com/a"],
                fetch_budget=3,
                llm_budget=0,
                deadline=time.monotonic() - 1,
            )
        )
    finally:
        species_bing.BingSpeciesProvider._fetch_pages = original
    assert called["n"] == 0
    assert result == ["鲤鱼"]
    assert fetches == 0


def test_a_hung_page_cannot_make_the_whole_batch_time_out():
    """End to end: the batch finishes inside its own budget, not the caller's.

    This is the shape that reached the phones: the serp was fine, one result
    page hung, and the batch ran past the provider budget until the caller's
    ``wait_for`` cancelled it. The spot's snippet hits were already resolved by
    then, so the user lost a result we actually had.
    """
    from fishagent.providers import species_bing

    async def hang(self, client, urls):
        await asyncio.sleep(60)
        return []

    provider = species_bing.BingSpeciesProvider(
        timeout_seconds=0.6, extractor=None, enable_page_fetch=True
    )

    class _Client:
        pass

    original = species_bing.BingSpeciesProvider._fetch_pages
    species_bing.BingSpeciesProvider._fetch_pages = hang

    async def batch():
        started = time.monotonic()
        deepened = await asyncio.gather(
            *(
                provider._deepen(
                    _Client(),
                    ["鲫鱼"],
                    ["https://example.com/hung"],
                    fetch_budget=3,
                    llm_budget=0,
                    deadline=started + 0.3,
                )
                for _ in range(4)
            )
        )
        return deepened, time.monotonic() - started

    try:
        deepened, elapsed = asyncio.run(asyncio.wait_for(batch(), timeout=30))
    finally:
        species_bing.BingSpeciesProvider._fetch_pages = original

    assert [species for species, _, _ in deepened] == [["鲫鱼"]] * 4
    assert elapsed < 2.0, f"a hung page held the batch for {elapsed:.2f}s"


# --- bait suggestions -------------------------------------------------------
#
# Each spot card shows "推荐鱼种" and then "推荐饵料" underneath. The bait has to
# come from the species on that same card: computing it independently would let
# a card recommend bait for a fish it just said was not there.


def test_baits_follow_the_species_list(client):
    payload = client.post("/api/spots/species", json={"spots": MOCK_SPOTS}).json()
    for item in payload["results"]:
        if not item["species"]:
            assert item["baits"] == [], item
            continue
        assert [bait["species"] for bait in item["baits"]] == item["species"], item


def test_each_bait_entry_is_complete(client):
    payload = client.post("/api/spots/species", json={"spots": MOCK_SPOTS}).json()
    entries = [bait for item in payload["results"] for bait in item["baits"]]
    assert entries, "mock data should produce at least one bait plan"
    for bait in entries:
        assert set(bait) == {"species", "main", "nest", "tip", "generic"}
        assert bait["main"].strip(), bait
        assert bait["tip"].strip(), bait
        assert isinstance(bait["generic"], bool)


def test_degraded_response_has_no_bait(client, override_provider):
    """A failed lookup must not leave bait on the card.

    Bait for a species we cannot confirm is present would read as a
    recommendation for this water body -- exactly the implication degradation
    is supposed to avoid.
    """

    class FailingProvider:
        name = "test"
        source_label = ""

        async def find_species(self, spots):
            raise RuntimeError("community lookup unavailable")

    override_provider(FailingProvider())
    payload = client.post("/api/spots/species", json={"spots": MOCK_SPOTS}).json()
    assert payload["degraded"] is True
    for item in payload["results"]:
        assert item["species"] == []
        assert item["baits"] == [], item


def test_empty_recommendation_has_no_bait(client, override_provider):
    override_provider(NullSpeciesProvider())
    payload = client.post("/api/spots/species", json={"spots": MOCK_SPOTS}).json()
    for item in payload["results"]:
        assert item["baits"] == [], item


def test_typical_fallback_still_gets_bait(client, override_provider):
    """When the card shows 'same-type common species', those species get bait
    too -- the whole point is that the bait matches what is displayed."""

    class EmptyButResolvesProvider:
        name = "test"
        source_label = ""
        # Found nothing, but it *did* look -- so the water-type fallback applies.
        resolves_empty = True

        async def find_species(self, spots):
            return [[] for _ in spots]

    override_provider(EmptyButResolvesProvider())
    response = client.post(
        "/api/spots/species",
        json={"spots": [{"name": "某个没查到的小水库", "water_type": "水库"}]},
    )
    assert response.status_code == 200, response.text
    item = response.json()["results"][0]
    assert item["source"] == "typical", item
    assert item["species"]
    assert [bait["species"] for bait in item["baits"]] == item["species"]
