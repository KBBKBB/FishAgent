from __future__ import annotations

import pytest
from conftest import (
    FORBIDDEN_SPOT_WORDS,
    HANGZHOU,
    assert_iso_utc,
    assert_unified_error,
    navigation_position,
    spot_params,
)

SPOT_KEYS = {
    "id",
    "name",
    "water_type",
    "address",
    "location_gcj02",
    "entry_location_gcj02",
    "entry_precision",
    "distance_m",
    "drive_seconds_out",
    "drive_seconds_back",
    "drive_seconds_round_trip",
    "drive_minutes_one_way",
    "fish_score",
    "total_score",
    "reasons",
    "navigation_url",
}


def get_spots(client, **overrides):
    response = client.get("/api/spots/recommend", params=spot_params(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def assert_filtered_invariant(payload):
    filtered = payload["filtered"]
    keys = {
        "total_candidates",
        "forbidden",
        "over_two_hours",
        "eligible",
        "returned",
        "truncated_by_limit",
    }
    assert set(filtered) >= keys, filtered
    for key in keys:
        assert isinstance(filtered[key], int) and filtered[key] >= 0, (key, filtered[key])

    # Everything recalled is accounted for exactly once: dropped for being
    # inside the ring, forbidden, evaluated (then kept or discarded), or not
    # evaluated at all. Duplicates collapse into "not evaluated" because that
    # is what happened to them.
    assert filtered["total_candidates"] == (
        filtered.get("within_min_radius", 0)
        + filtered["forbidden"]
        + filtered["evaluated"]
        + filtered["unevaluated"]
    ), filtered
    assert filtered["evaluated"] == (
        filtered["unavailable"] + filtered["over_two_hours"] + filtered["eligible"]
    ), filtered
    assert filtered["eligible"] == filtered["returned"] + filtered["truncated_by_limit"], filtered
    assert filtered["returned"] == len(payload["spots"]), filtered


def test_default_recommendation_contract(client):
    payload = get_spots(client)
    assert set(payload) >= {"user_location", "spots", "filtered", "meta"}

    user_location = payload["user_location"]
    assert user_location["wgs84"]["lat"] == pytest.approx(HANGZHOU["lat"], abs=1e-6)
    assert user_location["wgs84"]["lon"] == pytest.approx(HANGZHOU["lon"], abs=1e-6)
    assert user_location["gcj02"]["lat"] != pytest.approx(HANGZHOU["lat"], abs=1e-9)
    assert user_location["gcj02"]["lon"] != pytest.approx(HANGZHOU["lon"], abs=1e-9)

    meta = payload["meta"]
    assert meta["mock_mode"] is True
    assert meta["radius_km"] == 100
    assert meta["round_trip_limit_seconds"] == 7200
    assert meta["traffic_basis"] == "baseline_estimate"
    assert_iso_utc(meta["generated_at"])

    assert 1 <= len(payload["spots"]) <= 5
    for spot in payload["spots"]:
        assert SPOT_KEYS <= set(spot), f"missing spot fields: {SPOT_KEYS - set(spot)}"
        assert spot["entry_precision"] in {"entr_location", "center_fallback"}
        assert spot["distance_m"] > 0
        assert spot["drive_seconds_out"] > 0
        assert spot["drive_seconds_back"] > 0
        assert spot["drive_seconds_round_trip"] == (
            spot["drive_seconds_out"] + spot["drive_seconds_back"]
        )
        assert spot["drive_seconds_round_trip"] <= 7200
        assert spot["drive_minutes_one_way"] == (spot["drive_seconds_out"] + 30) // 60
        assert 0 <= spot["fish_score"] <= 100
        assert 0 <= spot["total_score"] <= 100
        assert round(spot["total_score"], 1) == pytest.approx(spot["total_score"], abs=1e-9)
        assert 2 <= len(spot["reasons"]) <= 4
        assert all(isinstance(reason, str) and reason for reason in spot["reasons"])


def test_filtered_counters_and_invariants(client):
    payload = get_spots(client)
    assert_filtered_invariant(payload)

    filtered = payload["filtered"]
    assert filtered["total_candidates"] >= 8
    assert filtered["forbidden"] >= 1
    assert filtered["over_two_hours"] >= 2


def test_round_trip_filter_uses_both_directions(client):
    payload = get_spots(client)
    for spot in payload["spots"]:
        assert spot["drive_seconds_round_trip"] <= 7200
        assert spot["drive_seconds_round_trip"] == (
            spot["drive_seconds_out"] + spot["drive_seconds_back"]
        )
    assert payload["filtered"]["over_two_hours"] >= 2


def test_entry_location_precision_and_fallback(client):
    spots = get_spots(client)["spots"]
    precisions = {spot["entry_precision"] for spot in spots}
    assert "center_fallback" in precisions, f"missing center_fallback candidate: {precisions}"

    for spot in spots:
        if spot["entry_precision"] == "center_fallback":
            center = spot["location_gcj02"]
            entry = spot["entry_location_gcj02"]
            assert entry["lat"] == pytest.approx(center["lat"], abs=1e-6)
            assert entry["lon"] == pytest.approx(center["lon"], abs=1e-6)
            assert spot["drive_seconds_round_trip"] <= 7200


def test_forbidden_candidates_are_excluded(client):
    payload = get_spots(client)
    assert payload["filtered"]["forbidden"] >= 1
    for spot in payload["spots"]:
        for word in FORBIDDEN_SPOT_WORDS:
            assert word not in spot["name"], f"forbidden candidate leaked: {spot['name']}"
            assert word not in spot["address"], f"forbidden address leaked: {spot['address']}"


def test_sorting_and_limit(client):
    default = get_spots(client)
    scores = [spot["total_score"] for spot in default["spots"]]
    assert scores == sorted(scores, reverse=True)
    for left, right in zip(default["spots"], default["spots"][1:]):
        if left["total_score"] == right["total_score"]:
            assert left["drive_seconds_round_trip"] <= right["drive_seconds_round_trip"]

    top_one = get_spots(client, limit=1)
    assert len(top_one["spots"]) == 1
    assert top_one["spots"][0]["id"] == default["spots"][0]["id"]

    top_ten = get_spots(client, limit=10)
    assert len(top_ten["spots"]) <= 10
    assert_filtered_invariant(top_ten)
    assert top_ten["filtered"]["total_candidates"] == default["filtered"]["total_candidates"]
    assert top_ten["filtered"]["forbidden"] == default["filtered"]["forbidden"]
    assert top_ten["filtered"]["over_two_hours"] == default["filtered"]["over_two_hours"]
    assert top_ten["filtered"]["eligible"] == default["filtered"]["eligible"]


@pytest.mark.parametrize(
    "params,expected_status",
    [
        ({"radius_km": 1}, 200),
        ({"radius_km": 100}, 200),
        ({"radius_km": 150}, 200),
        ({"radius_km": 150.1}, 422),
        ({"radius_km": 0}, 422),
        ({"radius_km": -1}, 422),
        ({"limit": 1}, 200),
        ({"limit": 10}, 200),
        ({"limit": 0}, 422),
        ({"limit": 11}, 422),
    ],
)
def test_radius_and_limit_validation(client, params, expected_status):
    response = client.get("/api/spots/recommend", params=spot_params(**params))
    if expected_status == 200:
        assert response.status_code == 200, response.text
    else:
        assert_unified_error(response, expected_status)


def test_radius_150_uses_unique_candidates(client):
    payload = get_spots(client, radius_km=150)
    ids = [spot["id"] for spot in payload["spots"]]
    assert len(ids) == len(set(ids)), f"duplicate spot ids: {ids}"
    assert payload["meta"]["radius_km"] == 150
    assert_filtered_invariant(payload)


def test_radius_1_does_not_fail(client):
    payload = get_spots(client, radius_km=1)
    assert isinstance(payload["spots"], list)
    assert_filtered_invariant(payload)


@pytest.mark.parametrize(
    "offset,expected_status",
    [
        (0, 200),
        (5, 200),
        (20, 200),
        (-1, 422),
        (21, 422),
    ],
)
def test_offset_validation(client, offset, expected_status):
    response = client.get("/api/spots/recommend", params=spot_params(offset=offset))
    if expected_status == 200:
        assert response.status_code == 200, response.text
        assert_filtered_invariant(response.json())
    else:
        assert_unified_error(response, expected_status)


def test_offset_beyond_eligible_returns_empty_page(client):
    payload = get_spots(client, offset=20)
    assert payload["spots"] == []
    filtered = payload["filtered"]
    assert filtered["returned"] == 0
    assert filtered["truncated_by_limit"] == filtered["eligible"]
    assert_filtered_invariant(payload)


def test_offset_zero_matches_default(client):
    default = get_spots(client)
    explicit = get_spots(client, offset=0)
    assert [spot["id"] for spot in explicit["spots"]] == [
        spot["id"] for spot in default["spots"]
    ]
    assert explicit["filtered"] == default["filtered"]


def test_navigation_url_uses_entry_coordinates(client):
    for spot in get_spots(client)["spots"]:
        lat, lon = navigation_position(spot["navigation_url"])
        entry = spot["entry_location_gcj02"]
        assert lat == pytest.approx(entry["lat"], abs=1e-4), spot["navigation_url"]
        assert lon == pytest.approx(entry["lon"], abs=1e-4), spot["navigation_url"]


def test_valid_species_accepted(client):
    response = client.get("/api/spots/recommend", params=spot_params(species="鲫鱼"))
    assert response.status_code == 200, response.text
    assert response.json()["spots"]


def test_deterministic_for_same_input(client):
    first = get_spots(client)
    second = get_spots(client)
    assert [spot["id"] for spot in first["spots"]] == [spot["id"] for spot in second["spots"]]
    assert [spot["total_score"] for spot in first["spots"]] == [
        spot["total_score"] for spot in second["spots"]
    ]
    assert [spot["drive_seconds_round_trip"] for spot in first["spots"]] == [
        spot["drive_seconds_round_trip"] for spot in second["spots"]
    ]
    assert first["filtered"] == second["filtered"]
