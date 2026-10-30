"""Spot recommendations must not all come from one place.

Measured before this: from Chengdu with an 80 km radius, five returned spots
sat inside 7.7 km, and every one of them had the same fish score. Two causes
stacked up -- only the nearest batch was ever evaluated, and ranking degenerates
to "shortest round trip" when every candidate shares one fish score.

The shapes below are synthetic on purpose: they let a cluster be placed exactly
where the old code would have failed, which real AMap data cannot guarantee.
"""

from __future__ import annotations

import math

from fishagent.core.coords import haversine_m
from fishagent.schemas import LatLon, SpotCandidate
from fishagent.services import spots as spot_service

ORIGIN = LatLon(lat=30.657, lon=104.066)


def _candidate(index: int, distance_km: float, bearing_deg: float) -> SpotCandidate:
    radians = math.radians(bearing_deg)
    lat = ORIGIN.lat + (distance_km * math.cos(radians)) / 111.32
    lon = ORIGIN.lon + (distance_km * math.sin(radians)) / (
        111.32 * math.cos(math.radians(ORIGIN.lat))
    )
    return SpotCandidate(
        id=f"c{index:03d}",
        name=f"水域{index}",
        water_type="水库",
        address="测试地址",
        location_gcj02=LatLon(lat=lat, lon=lon),
    )


def clustered_pool() -> list[SpotCandidate]:
    """What real recall looks like: a dense core plus a thin far field.

    90% of candidates within 10 km, then out to 150 km. An equal-count band
    split passes on a uniform ring dataset and fails here, which is why this
    shape is the one used.
    """
    candidates: list[SpotCandidate] = []
    index = 0
    for bearing in range(0, 360, 45):
        for step in range(140):
            candidates.append(_candidate(index, 0.5 + step * 0.07, bearing))
            index += 1
    for bearing in range(10, 370, 45):
        for step in range(15):
            candidates.append(_candidate(index, 25 + step * 8, bearing))
            index += 1
    return sorted(
        candidates,
        key=lambda item: spot_service._candidate_distance_m(ORIGIN, item),
    )


def _distances(candidates: list[SpotCandidate]) -> list[float]:
    return [
        haversine_m(ORIGIN.lat, ORIGIN.lon, c.location_gcj02.lat, c.location_gcj02.lon)
        / 1000
        for c in candidates
    ]


def test_pool_reaches_beyond_the_dense_core():
    """A count-based band split leaves the pool inside the 10 km core."""
    pool = spot_service._sector_balanced_pool(ORIGIN, clustered_pool(), 40)
    assert len(pool) == 40
    farthest = max(_distances(pool))
    assert farthest > 50, f"pool still hugs the user: max {farthest:.1f} km"


def test_interleave_spans_the_radius_from_the_first_page():
    """The first evaluated batch must not be the nearest batch."""
    pool = spot_service._sector_balanced_pool(ORIGIN, clustered_pool(), 40)
    ordered = spot_service._interleave_sectors(ORIGIN, pool)
    first_ten = _distances(ordered[:10])
    assert max(first_ten) > 50, f"first batch is still local: {first_ten}"
    bands = sum(1 for distance in first_ten if distance > 20)
    assert bands >= 4, f"first batch covers too few distance bands: {first_ten}"


def test_interleave_keeps_every_candidate():
    """Paging must not silently drop spots."""
    pool = spot_service._sector_balanced_pool(ORIGIN, clustered_pool(), 40)
    ordered = spot_service._interleave_sectors(ORIGIN, pool)
    assert len(ordered) == len(pool)
    assert {item.id for item in ordered} == {item.id for item in pool}


def test_empty_and_tiny_inputs_do_not_crash():
    """A 1 km radius can recall nothing; that must not raise."""
    assert spot_service._sector_balanced_pool(ORIGIN, [], 10) == []
    assert spot_service._interleave_sectors(ORIGIN, []) == []
    one = [_candidate(0, 1.0, 0)]
    assert spot_service._sector_balanced_pool(ORIGIN, one, 10) == one
    assert spot_service._interleave_sectors(ORIGIN, one) == one


def test_all_candidates_are_kept_when_pool_is_not_narrowed():
    candidates = clustered_pool()[:20]
    assert spot_service._sector_balanced_pool(ORIGIN, candidates, 40) == candidates


def _named(index: int, name: str, distance_km: float) -> SpotCandidate:
    return SpotCandidate(
        id=f"n{index:03d}",
        name=name,
        water_type="河流",
        address="测试地址",
        location_gcj02=LatLon(lat=ORIGIN.lat + distance_km / 111.32, lon=ORIGIN.lon),
    )


def test_same_river_under_several_names_is_collapsed():
    """AMap lists one river as 府河 / 府河(锦江) / 府河（锦江）.

    Three cards reading 府河 give the user nothing to choose between, and each
    duplicate costs a drive estimate to discover what the name already said.
    """
    candidates = [
        _named(0, "府河", 2.0),
        _named(1, "府河(锦江)", 3.0),
        _named(2, "府河（锦江）", 4.0),
        _named(3, "沙河", 5.0),
    ]
    kept = spot_service._collapse_duplicate_candidates(candidates)
    assert [c.name for c in kept] == ["府河", "沙河"]


def test_similar_but_different_waters_are_kept():
    """圣河 and 沙河 differ by one character and are different waters."""
    candidates = [
        _named(0, "圣河", 2.0),
        _named(1, "沙河", 3.0),
        _named(2, "清水河", 4.0),
    ]
    kept = spot_service._collapse_duplicate_candidates(candidates)
    assert len(kept) == 3


def test_name_normalisation_strips_spacing_and_brackets():
    assert spot_service._water_key_text(" 府河（锦江） ") == "府河"
    assert spot_service._water_key_text("府 河") == "府河"
    assert spot_service._water_key_text("") == ""


def test_separation_target_scales_with_radius():
    small = spot_service._separation_target_m(5_000, 5)
    large = spot_service._separation_target_m(150_000, 5)
    assert small < large
    # A tiny search must not demand a huge gap.
    assert small <= spot_service._MIN_SEPARATION_FLOOR_M * 2


def test_separation_target_never_exceeds_the_ceiling():
    assert (
        spot_service._separation_target_m(10_000_000, 1)
        <= spot_service._MIN_SEPARATION_CEIL_M
    )
