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


def test_stops_after_nearest_batch_meets_limit(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client)
    filtered = payload["filtered"]

    assert [spot["id"] for spot in payload["spots"]] == [
        "perf_000",
        "perf_001",
        "perf_002",
        "perf_003",
        "perf_004",
    ]
    assert filtered == {
        "total_candidates": 120,
        "forbidden": 0,
        "unavailable": 0,
        "over_two_hours": 0,
        "eligible": 10,
        "returned": 5,
        "truncated_by_limit": 5,
        "evaluated": 10,
        "unevaluated": 110,
    }
    assert geo.drive_calls == 20
    assert 1 < geo.max_active <= get_settings().amap_concurrency
    assert all(spot["drive_seconds_round_trip"] <= 7200 for spot in payload["spots"])


def test_limit_ten_evaluates_one_ten_candidate_batch(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client, limit=10)
    filtered = payload["filtered"]

    assert [spot["id"] for spot in payload["spots"]] == [
        f"perf_{index:03d}" for index in range(10)
    ]
    assert filtered["evaluated"] == 10
    assert filtered["eligible"] == 10
    assert filtered["returned"] == 10
    assert filtered["truncated_by_limit"] == 0
    assert filtered["unevaluated"] == 110
    assert geo.drive_calls == 20


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
    assert geo.drive_calls == 60


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
    assert first_ids == [f"perf_{index:03d}" for index in range(5)]
    assert second_ids == [f"perf_{index:03d}" for index in range(5, 10)]
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

    assert [spot["id"] for spot in payload["spots"]] == [
        f"perf_{index:03d}" for index in range(6, 11)
    ]
    assert filtered == {
        "total_candidates": 120,
        "forbidden": 0,
        "unavailable": 0,
        "over_two_hours": 0,
        "eligible": 20,
        "returned": 5,
        "truncated_by_limit": 15,
        "evaluated": 20,
        "unevaluated": 100,
    }
    assert geo.drive_calls == 40


def test_max_offset_and_limit_reach_evaluation_cap(client, install_overrides):
    geo = FakeGeoProvider(make_candidates(120), lambda index: 60 + index * 10)
    install_overrides(geo)

    payload = get_spots(client, limit=10, offset=20)
    filtered = payload["filtered"]

    assert [spot["id"] for spot in payload["spots"]] == [
        f"perf_{index:03d}" for index in range(20, 30)
    ]
    assert filtered["evaluated"] == 30
    assert filtered["eligible"] == 30
    assert filtered["returned"] == 10
    assert filtered["truncated_by_limit"] == 20
    assert filtered["unevaluated"] == 90
    assert geo.drive_calls == 60


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
