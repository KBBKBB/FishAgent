from __future__ import annotations

import asyncio

import pytest
from conftest import HANGZHOU

from fishagent.config import get_settings
from fishagent.deps import get_geo_provider, get_weather_provider
from fishagent.main import app
from fishagent.providers.base import ProviderError
from fishagent.providers.weather_mock import MockWeatherProvider
from fishagent.schemas import LatLon, SpotCandidate


def make_candidates(count: int) -> list[SpotCandidate]:
    return [
        SpotCandidate(
            id=f"perf_{index:03d}",
            name=f"测试水库{index}",
            water_type="水库",
            address="测试地址",
            location_gcj02=LatLon(
                lat=HANGZHOU["lat"] + index * 0.0002,
                lon=HANGZHOU["lon"],
            ),
        )
        for index in range(count)
    ]


class FakeGeoProvider:
    def __init__(self, candidates, out_seconds, unavailable_ids=()):
        self.candidates = candidates
        self.out_seconds = out_seconds
        self.unavailable_ids = set(unavailable_ids)
        self.active = 0
        self.max_active = 0
        self.recall_calls = 0
        self.drive_calls = 0

    async def find_water_spots(self, origin, center, radius_m):
        self.recall_calls += 1
        return await self._run(lambda: self.candidates)

    async def estimate_drive_seconds(
        self,
        origin,
        destination,
        departure_at,
        direction,
        route_key="",
    ):
        self.drive_calls += 1
        index = int(route_key.split("_")[-1])
        return await self._run(lambda: self._duration(route_key, index))

    def _duration(self, route_key: str, index: int) -> int:
        if route_key in self.unavailable_ids:
            raise ProviderError("synthetic drive failure")
        return self.out_seconds(index)

    async def _run(self, action):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)
            return action()
        finally:
            self.active -= 1


@pytest.fixture()
def install_overrides():
    def install(geo_provider):
        app.dependency_overrides[get_geo_provider] = lambda: geo_provider
        app.dependency_overrides[get_weather_provider] = lambda: MockWeatherProvider()

    yield install
    app.dependency_overrides.pop(get_geo_provider, None)
    app.dependency_overrides.pop(get_weather_provider, None)


def get_spots(client, **overrides):
    params = dict(HANGZHOU)
    params.update(overrides)
    response = client.get("/api/spots/recommend", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_stops_after_one_batch_meets_limit(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client)
    filtered = payload["filtered"]

    # The exact ids are no longer "the five nearest": spreading picks from
    # across the batch. What must not change is the cost -- one batch of ten
    # drive calls, not the whole candidate list.
    assert filtered == {
        "total_candidates": 120,
        "within_min_radius": 0,
        "forbidden": 0,
        "unavailable": 0,
        "over_two_hours": 0,
        "eligible": 10,
        "returned": 5,
        "truncated_by_limit": 5,
        "evaluated": 10,
        "unevaluated": 110,
    }
    assert geo.drive_calls == 10
    assert 1 < geo.max_active <= get_settings().amap_concurrency
    assert all(spot["drive_seconds_round_trip"] <= 7200 for spot in payload["spots"])
    # Returned spots must still be ranked best-first.
    scores = [spot["total_score"] for spot in payload["spots"]]
    assert scores == sorted(scores, reverse=True)


def test_first_page_is_not_all_from_one_place(client, install_overrides):
    """The regression this strategy exists for.

    Five candidates could be the five nearest, which put every card within a
    few kilometres of the user. The synthetic candidates here sit in a straight
    line 22 m apart, so "nearest five" is trivially the first five ids; a
    spread result must skip ahead instead.
    """
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    ids = [spot["id"] for spot in get_spots(client)["spots"]]
    assert ids != [f"perf_{index:03d}" for index in range(5)], (
        f"first page is still the five nearest candidates: {ids}"
    )


def test_limit_ten_evaluates_one_ten_candidate_batch(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client, limit=10)
    filtered = payload["filtered"]

    assert len(payload["spots"]) == 10
    assert filtered["evaluated"] == 10
    assert filtered["eligible"] == 10
    assert filtered["returned"] == 10
    assert filtered["truncated_by_limit"] == 0
    assert filtered["unevaluated"] == 110
    assert geo.drive_calls == 10


def test_expands_evaluation_batches_until_limit_is_met(client, install_overrides):
    def out_seconds(index: int) -> int:
        return 60 if index < 2 or 20 <= index < 23 else 4000

    geo = FakeGeoProvider(make_candidates(120), out_seconds)
    install_overrides(geo)

    payload = get_spots(client)
    filtered = payload["filtered"]

    assert [spot["id"] for spot in payload["spots"]] == [
        "perf_000",
        "perf_001",
        "perf_020",
        "perf_021",
        "perf_022",
    ]
    assert filtered["evaluated"] == 30
    assert filtered["unevaluated"] == 90
    assert filtered["eligible"] == 5
    assert filtered["over_two_hours"] == 25
    assert filtered["returned"] == 5
    assert filtered["truncated_by_limit"] == 0
    assert geo.drive_calls == 30


def test_unavailable_drives_are_counted_separately(client, install_overrides):
    geo = FakeGeoProvider(
        make_candidates(30),
        lambda index: 60 + index * 10,
        unavailable_ids={"perf_000", "perf_001"},
    )
    install_overrides(geo)

    payload = get_spots(client)
    filtered = payload["filtered"]

    assert filtered["unavailable"] == 2
    assert filtered["over_two_hours"] == 0
    assert filtered["eligible"] == 8
    assert filtered["evaluated"] == 10
    assert filtered["unevaluated"] == 20
    assert filtered["truncated_by_limit"] == 3
    assert filtered["total_candidates"] == 30
    assert len(payload["spots"]) == 5


def test_offset_returns_next_ranked_page(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    first = get_spots(client, limit=5, offset=0)
    second = get_spots(client, limit=5, offset=5)

    first_ids = [spot["id"] for spot in first["spots"]]
    second_ids = [spot["id"] for spot in second["spots"]]
    # Which ids land on which page changed with the spread strategy; that the
    # two pages are disjoint and each holds a full page did not.
    assert len(first_ids) == len(set(first_ids)) == 5
    assert len(second_ids) == len(set(second_ids)) == 5
    assert set(first_ids).isdisjoint(second_ids)
    for payload in (first, second):
        filtered = payload["filtered"]
        assert filtered["returned"] == len(payload["spots"]) == 5
        assert filtered["eligible"] == filtered["returned"] + filtered["truncated_by_limit"]
        assert filtered["evaluated"] == 10
        assert filtered["unevaluated"] == 110


def test_offset_expands_evaluation_window(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client, limit=5, offset=6)
    filtered = payload["filtered"]

    assert len(payload["spots"]) == 5
    assert filtered == {
        "total_candidates": 120,
        "within_min_radius": 0,
        "forbidden": 0,
        "unavailable": 0,
        "over_two_hours": 0,
        "eligible": 20,
        "returned": 5,
        "truncated_by_limit": 15,
        "evaluated": 20,
        "unevaluated": 100,
    }
    assert geo.drive_calls == 20


def test_max_offset_and_limit_reach_evaluation_cap(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client, limit=10, offset=20)
    filtered = payload["filtered"]

    assert len(payload["spots"]) == 10
    assert filtered["evaluated"] == 30
    assert filtered["eligible"] == 30
    assert filtered["returned"] == 10
    assert filtered["truncated_by_limit"] == 20
    assert filtered["unevaluated"] == 90
    assert geo.drive_calls == 30


def test_offset_beyond_eligible_returns_empty_page(client, install_overrides):
    geo = FakeGeoProvider(
        make_candidates(30),
        lambda index: 60 if index < 2 else 4000,
    )
    install_overrides(geo)

    payload = get_spots(client, limit=5, offset=5)
    filtered = payload["filtered"]

    assert payload["spots"] == []
    assert filtered["eligible"] == 2
    assert filtered["returned"] == 0
    assert filtered["truncated_by_limit"] == 2
    assert filtered["evaluated"] == 30
    assert filtered["unevaluated"] == 0
    assert filtered["total_candidates"] == 30


def test_mock_mode_still_evaluates_every_candidate(client):
    payload = get_spots(client)
    filtered = payload["filtered"]

    assert filtered["unevaluated"] == 0
    assert filtered["unavailable"] == 0
    assert filtered["evaluated"] == filtered["total_candidates"] - filtered["forbidden"]
    assert filtered["total_candidates"] == (
        filtered["forbidden"] + filtered["unavailable"] + filtered["over_two_hours"]
        + filtered["eligible"]
    )
    assert [spot["id"] for spot in payload["spots"]] == [
        "mock_spot_001",
        "mock_spot_002",
        "mock_spot_003",
        "mock_spot_006",
        "mock_spot_004",
    ]


# --- latency regression guards ----------------------------------------------
#
# A cold recommendation took 14 s: every evaluated candidate issued two
# identical AMap requests (the live provider ignores ``direction``) and nothing
# was cached, so each page load paid the full cost again.


def test_live_provider_issues_one_drive_call_per_candidate(client, install_overrides):
    """Out and back must not both hit the quota-limited API."""
    geo = FakeGeoProvider(make_candidates(30), lambda index: 300)
    install_overrides(geo)

    get_spots(client, limit=10)

    # 10 evaluated candidates -> 10 calls, not 20.
    assert geo.drive_calls == 10


def test_provider_that_uses_direction_still_gets_both_calls(client, install_overrides):
    """A provider whose result depends on direction must not be short-changed."""
    geo = FakeGeoProvider(make_candidates(30), lambda index: 300)
    geo.direction_affects_result = True
    install_overrides(geo)

    get_spots(client, limit=10)

    assert geo.drive_calls == 20, "direction-sensitive providers need out and back"


def test_repeat_request_is_served_from_cache(client, install_overrides):
    """The page refetches on every load; the second one must not re-evaluate."""
    geo = FakeGeoProvider(make_candidates(30), lambda index: 300)
    install_overrides(geo)

    first = get_spots(client, limit=10)
    calls_after_first = geo.drive_calls
    second = get_spots(client, limit=10)

    assert geo.drive_calls == calls_after_first, "cached response must not re-query AMap"
    assert [s["id"] for s in second["spots"]] == [s["id"] for s in first["spots"]]


def test_cache_key_separates_radius_and_limit(client, install_overrides):
    """A different radius is a different question and must not be cache-served."""
    geo = FakeGeoProvider(make_candidates(30), lambda index: 300)
    install_overrides(geo)

    get_spots(client, limit=10, radius_km=50)
    after_first = geo.drive_calls
    get_spots(client, limit=5, radius_km=20)

    assert geo.drive_calls > after_first, "changed parameters must bypass the cache"


def test_cache_expires(client, install_overrides, monkeypatch):
    """A stale entry must be recomputed rather than served indefinitely."""
    import fishagent.services.spots as spots_service

    geo = FakeGeoProvider(make_candidates(30), lambda index: 300)
    install_overrides(geo)
    monkeypatch.setattr(spots_service, "_CACHE_TTL_SECONDS", 0, raising=True)

    get_spots(client, limit=10)
    after_first = geo.drive_calls
    get_spots(client, limit=10)

    assert geo.drive_calls > after_first, "TTL 0 must disable caching"
