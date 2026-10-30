"""Search radius is a ring, not just a cap.

"10~50 km" must exclude the water nearer than 10 km as well as the water past
50. This matters because the near field is where the highest-scoring spots
usually are: without the inner edge, a user asking for "a bit further out"
would just get the same few closest spots back.
"""

from __future__ import annotations

import pytest
from conftest import assert_unified_error, spot_params


def get_spots(client, **overrides):
    response = client.get("/api/spots/recommend", params=spot_params(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def test_min_radius_excludes_the_near_field(client):
    wide = get_spots(client, min_radius_km=0, radius_km=150)
    ring = get_spots(client, min_radius_km=50, radius_km=150)

    assert ring["spots"], "a 50-150 km ring should still have something in mock data"
    for spot in ring["spots"]:
        assert spot["distance_m"] >= 50_000, spot["name"]
    # And the ring is a strict subset of the circle, not a reshuffle.
    assert len(ring["spots"]) < len(wide["spots"])


def test_ring_bounds_are_reflected_in_meta(client):
    payload = get_spots(client, min_radius_km=10, radius_km=50)
    assert payload["meta"]["min_radius_km"] == 10
    assert payload["meta"]["radius_km"] == 50


def test_zero_min_radius_keeps_the_old_behaviour(client):
    """The default call must be unchanged: min 0 means "everything inside"."""
    default = get_spots(client)
    explicit = get_spots(client, min_radius_km=0)
    assert [s["id"] for s in default["spots"]] == [s["id"] for s in explicit["spots"]]
    assert all(spot["distance_m"] >= 0 for spot in default["spots"])


def test_inner_radius_is_counted_so_the_totals_add_up(client):
    payload = get_spots(client, min_radius_km=50, radius_km=150)
    filtered = payload["filtered"]
    assert filtered["within_min_radius"] > 0
    assert filtered["total_candidates"] == (
        filtered["within_min_radius"]
        + filtered["forbidden"]
        + filtered["evaluated"]
        + filtered["unevaluated"]
    ), filtered


def test_inverted_range_is_rejected(client):
    response = client.get(
        "/api/spots/recommend", params=spot_params(min_radius_km=100, radius_km=50)
    )
    assert_unified_error(response, 422, "INVALID_RADIUS_RANGE")


def test_equal_bounds_are_rejected(client):
    """An empty ring (50~50 km) is a mistake, not a query."""
    response = client.get(
        "/api/spots/recommend", params=spot_params(min_radius_km=50, radius_km=50)
    )
    assert_unified_error(response, 422, "INVALID_RADIUS_RANGE")


@pytest.mark.parametrize("min_radius", [-1, 200])
def test_min_radius_is_range_checked(client, min_radius):
    response = client.get(
        "/api/spots/recommend", params=spot_params(min_radius_km=min_radius)
    )
    assert_unified_error(response, 422)


def test_ring_and_circle_do_not_share_a_cache_entry():
    """10~50 and 0~50 are different searches.

    Asserted on the key rather than on the results: with mock data every spot
    inside the 10-50 ring may also be inside 0-50, so equal result sets would
    be a legitimate outcome and the test would prove nothing.
    """
    from fishagent.services import spots as spot_service

    circle = spot_service._spot_cache_key(
        lat=1.0, lon=2.0, min_radius_km=0, radius_km=50, limit=5, species=None, offset=0
    )
    ring = spot_service._spot_cache_key(
        lat=1.0, lon=2.0, min_radius_km=10, radius_km=50, limit=5, species=None, offset=0
    )
    assert circle != ring
