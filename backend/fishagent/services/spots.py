"""Spot recommendation: sharded recall -> forbidden -> round-trip -> rank."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import quote

from fishagent.config import get_settings
from fishagent.core.coords import haversine_m, wgs84_to_gcj02
from fishagent.core.forbidden import forbidden_reason
from fishagent.core.rules import compute_fish_activity
from fishagent.errors import ApiError
from fishagent.providers.base import (
    GeoProvider,
    ProviderError,
    UpstreamQuotaExceeded,
    WeatherProvider,
)
from fishagent.schemas import (
    FilteredStats,
    LatLon,
    SpotCandidate,
    SpotOut,
    SpotRecommendationResponse,
    SpotsMeta,
    UserLocationOut,
)
from fishagent.services.fish_activity import utc_timestamp, validate_species

logger = logging.getLogger(__name__)

ROUND_TRIP_LIMIT_SECONDS = 7200
MAX_PROVIDER_RADIUS_M = 50_000
TRAFFIC_BASIS = "baseline_estimate"
_GRID_SPACING_M = 70_000
_DEFAULT_FISH_SCORE = 60
_DEFAULT_FISH_BAND = "一般"
_MAX_EVALUATED_CANDIDATES = 30
_MIN_EVALUATION_BATCH = 10
# How many extra candidates beyond a full page are worth measuring, and the
# floor the pool never goes below. The floor exists because a good spot that
# nobody measured cannot be returned: with scattered qualifying candidates, a
# shallow pool came back with two cards where the deeper one filled five.
_POOL_SLACK = 6
_POOL_FLOOR = 30
_SELECTION_STRATEGY = "sector_greedy_spacing"
_BATCH_SCREEN_LIMIT = 100

# A full recommendation costs ~60 AMap drive calls (two per evaluated spot), so
# it takes 13-15 s cold. The page requests it on every load, which meant every
# visitor paid that. Cached by (rounded location, radius, limit, species, offset)
# with a short TTL: drive times are traffic estimates, so they go stale quickly,
# but a few minutes is well inside the noise of an estimate that already
# assumes baseline traffic.
_CACHE_TTL_SECONDS = 180
_MAX_CACHE_ENTRIES = 256
_spot_cache: OrderedDict[tuple, "_SpotCacheEntry"] = OrderedDict()
_spot_cache_lock = threading.Lock()


class _SpotCacheEntry:
    __slots__ = ("response", "expires_at")

    def __init__(self, response: SpotRecommendationResponse, expires_at: float) -> None:
        self.response = response
        self.expires_at = expires_at


def reset_spot_cache() -> None:
    """Test/ops hook: drop cached spot recommendations."""
    with _spot_cache_lock:
        _spot_cache.clear()


def _spot_cache_key(
    *,
    lat: float,
    lon: float,
    min_radius_km: float,
    radius_km: float,
    limit: int,
    species: str | None,
    offset: int,
) -> tuple:
    # Coordinates are rounded to ~100 m so trivial GPS jitter still hits the
    # cache; anything finer would produce a new key per request and never hit.
    # The inner radius is part of the key: 10~50 km and 0~50 km are different
    # searches and would otherwise answer each other.
    return (
        round(lat, 3),
        round(lon, 3),
        round(float(min_radius_km), 2),
        round(float(radius_km), 2),
        int(limit),
        species or "",
        int(offset),
    )


def _read_spot_cache(key: tuple, now: float) -> SpotRecommendationResponse | None:
    with _spot_cache_lock:
        entry = _spot_cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            _spot_cache.pop(key, None)
            return None
        _spot_cache.move_to_end(key)  # LRU: keep recently used entries
        return entry.response


def _write_spot_cache(key: tuple, response: SpotRecommendationResponse, now: float) -> None:
    if _CACHE_TTL_SECONDS <= 0:
        return
    with _spot_cache_lock:
        _spot_cache[key] = _SpotCacheEntry(response, now + _CACHE_TTL_SECONDS)
        _spot_cache.move_to_end(key)
        while len(_spot_cache) > _MAX_CACHE_ENTRIES:
            _spot_cache.popitem(last=False)


def _grid_centers(origin: LatLon, radius_m: float) -> list[LatLon]:
    """Search circles of <=50 km; a 70 km grid keeps any point within 50 km."""
    if radius_m <= MAX_PROVIDER_RADIUS_M:
        return [origin]

    extent = radius_m + MAX_PROVIDER_RADIUS_M
    steps = int(math.ceil(extent / _GRID_SPACING_M))
    lat_degree_m = 111_320.0
    lon_degree_m = max(111_320.0 * math.cos(math.radians(origin.lat)), 1.0)
    centers: list[LatLon] = []
    for north_index in range(-steps, steps + 1):
        north = north_index * _GRID_SPACING_M
        for east_index in range(-steps, steps + 1):
            east = east_index * _GRID_SPACING_M
            if math.hypot(east, north) > extent:
                continue
            centers.append(
                LatLon(
                    lat=origin.lat + north / lat_degree_m,
                    lon=origin.lon + east / lon_degree_m,
                )
            )
    return centers


async def _recall(
    provider: GeoProvider,
    origin: LatLon,
    radius_m: float,
    semaphore: asyncio.Semaphore,
) -> list[SpotCandidate]:
    call_radius = int(min(radius_m, MAX_PROVIDER_RADIUS_M))
    candidates: dict[str, SpotCandidate] = {}
    failures = 0

    async def fetch(center: LatLon) -> list[SpotCandidate] | None:
        async with semaphore:
            try:
                return await provider.find_water_spots(origin, center, call_radius)
            except ProviderError:
                logger.warning("water spot recall failed for one shard", exc_info=True)
                return None

    results = await asyncio.gather(*(fetch(center) for center in _grid_centers(origin, radius_m)))
    for found in results:
        if found is None:
            failures += 1
            continue
        for candidate in found:
            key = candidate.id or (
                f"{candidate.name}|{candidate.location_gcj02.lat:.6f},"
                f"{candidate.location_gcj02.lon:.6f}"
            )
            candidates.setdefault(key, candidate)
    if not candidates and failures:
        raise ApiError(
            status_code=502,
            code="GEO_PROVIDER_ERROR",
            message="钓位数据暂时不可用，请稍后再试",
        )
    return list(candidates.values())


async def _drive_seconds(
    provider: GeoProvider,
    origin: LatLon,
    destination: LatLon,
    departure: datetime,
    direction: str,
    route_key: str,
) -> int:
    try:
        return int(
            await provider.estimate_drive_seconds(
                origin, destination, departure, direction, route_key
            )
        )
    except TypeError:
        # Lightweight test doubles may omit the optional route_key parameter.
        return int(
            await provider.estimate_drive_seconds(origin, destination, departure, direction)
        )


async def _baseline_fish_score(
    provider: WeatherProvider,
    lat: float,
    lon: float,
    departure: datetime,
    species: str | None,
) -> tuple[int, str]:
    try:
        weather = await provider.get_weather(lat, lon, departure, None)
    except ProviderError:
        logger.warning("weather provider unavailable for spot fish_score", exc_info=True)
        return _DEFAULT_FISH_SCORE, _DEFAULT_FISH_BAND
    activity = compute_fish_activity(weather, departure, species)
    return activity.score, activity.band


def _travel_score(round_trip_seconds: int) -> float:
    ratio = round_trip_seconds / (2 * ROUND_TRIP_LIMIT_SECONDS)
    return max(0.0, min(100.0, 100.0 * (1.0 - ratio)))


def _navigation_url(entry: LatLon, name: str) -> str:
    return (
        "https://uri.amap.com/marker"
        f"?position={entry.lon:.6f},{entry.lat:.6f}"
        f"&name={quote(name, safe='')}"
        "&coordinate=gaode&callnative=1"
    )


def _one_way_minutes(drive_seconds_out: int) -> int:
    return (int(drive_seconds_out) + 30) // 60


def _build_spot(
    candidate: SpotCandidate,
    *,
    origin_gcj: LatLon,
    out_seconds: int,
    back_seconds: int,
    fish_score: int,
    fish_band: str,
) -> SpotOut:
    entry = candidate.entry_location_gcj02 or candidate.location_gcj02
    precision = "entr_location" if candidate.entry_location_gcj02 else "center_fallback"
    round_trip = out_seconds + back_seconds
    distance_m = int(
        round(
            haversine_m(
                origin_gcj.lat,
                origin_gcj.lon,
                candidate.location_gcj02.lat,
                candidate.location_gcj02.lon,
            )
        )
    )
    total_score = round(
        0.65 * fish_score + 0.35 * _travel_score(round_trip),
        1,
    )
    reasons = [
        f"往返约 {round_trip / 60:.0f} 分钟，单程约 {_one_way_minutes(out_seconds)} 分钟",
        f"{candidate.water_type}水域：{candidate.address or '地址待补充'}",
        f"鱼口评分 {fish_score}（{fish_band}）"
        + ("，下风口 +3" if candidate.downwind else ""),
        f"综合评分 {total_score:.1f}，距你约 {distance_m / 1000:.1f}km",
    ]
    return SpotOut(
        id=candidate.id,
        name=candidate.name,
        water_type=candidate.water_type,
        address=candidate.address,
        location_gcj02=candidate.location_gcj02,
        entry_location_gcj02=entry,
        entry_precision=precision,
        distance_m=distance_m,
        drive_seconds_out=out_seconds,
        drive_seconds_back=back_seconds,
        drive_seconds_round_trip=round_trip,
        drive_minutes_one_way=_one_way_minutes(out_seconds),
        fish_score=fish_score,
        total_score=total_score,
        reasons=reasons,
        navigation_url=_navigation_url(entry, candidate.name),
    )


def _candidate_distance_m(origin_gcj: LatLon, candidate: SpotCandidate) -> float:
    return haversine_m(
        origin_gcj.lat,
        origin_gcj.lon,
        candidate.location_gcj02.lat,
        candidate.location_gcj02.lon,
    )


async def _order_by_batch_return(
    provider: GeoProvider,
    origin: LatLon,
    candidates: list[SpotCandidate],
) -> list[SpotCandidate]:
    """Use AMap's one-to-many distance API to prioritize by real return time.

    Screening only reorders candidates; every candidate that is finally
    evaluated still gets separate outbound and return-path estimates.
    """
    batch_method = getattr(provider, "estimate_batch_drive_seconds", None)
    if batch_method is None or len(candidates) < 2:
        return candidates
    screened = candidates[:_BATCH_SCREEN_LIMIT]
    entries = [
        candidate.entry_location_gcj02 or candidate.location_gcj02
        for candidate in screened
    ]
    try:
        durations = await batch_method(origin, entries)
    except ProviderError:
        logger.warning("batch return screen failed; keeping distance order", exc_info=True)
        return candidates
    if not durations or len(durations) < len(screened):
        return candidates
    if all(duration is None for duration in durations):
        return candidates
    order = sorted(
        range(len(screened)),
        key=lambda index: (
            durations[index] if durations[index] is not None else math.inf,
            index,
        ),
    )
    return [screened[index] for index in order] + candidates[_BATCH_SCREEN_LIMIT:]


# --- Spreading the recommendation out -------------------------------------
#
# The evaluation loop stops as soon as it has ``limit`` usable spots, and it
# walks candidates in travel-time order, so the returned set used to be the
# nearest handful that happened to fit: measured from Chengdu, five spots inside
# 7.7 km with a 80 km search radius. Two separate causes stacked up:
#
#   1. Only the first batch was ever looked at. With 448 candidates, 438 were
#      never evaluated, so any distant-but-good spot could not be selected.
#   2. Ranking is 0.65 * fish_score + 0.35 * travel_score, and fish_score is
#      computed once at the user's location -- identical for every candidate
#      bar a +3 downwind bonus. Ranking therefore degenerates to "shortest
#      round trip", and sorting then picking the top N can only ever return a
#      cluster around the user.
#
# Fixing (2) properly means scoring each spot's own weather, which is a
# separate change (one more upstream call per candidate). What this does
# instead is make the *candidate pool* spatial and then enforce spacing, so a
# good spot further out can win when it is genuinely better on the numbers we
# already have.

_SECTOR_COUNT = 8
# Distance bands drawn from inside each sector, so the pool reaches across the
# search radius instead of hugging the user.
_POOL_DISTANCE_BANDS = 4
_MIN_SEPARATION_RATIO = 0.35
_MIN_SEPARATION_FLOOR_M = 3_000.0
_MIN_SEPARATION_CEIL_M = 25_000.0


def _bearing_sector(origin_gcj: LatLon, candidate: SpotCandidate) -> int:
    """Compass sector (0-7) of the candidate as seen from the user."""
    d_lat = candidate.location_gcj02.lat - origin_gcj.lat
    d_lon = (candidate.location_gcj02.lon - origin_gcj.lon) * math.cos(
        math.radians(origin_gcj.lat)
    )
    if d_lat == 0 and d_lon == 0:
        return 0
    angle = math.degrees(math.atan2(d_lat, d_lon)) % 360.0
    return int(angle // (360.0 / _SECTOR_COUNT)) % _SECTOR_COUNT


def _sector_balanced_pool(
    origin_gcj: LatLon,
    candidates: list[SpotCandidate],
    slots: int,
) -> list[SpotCandidate]:
    """Sample the candidate set across directions *and* distances.

    Balancing by direction alone is not enough, and the measurement is the
    reason: from Chengdu with a 150 km radius, 1246 candidates were recalled,
    the pool took the nearest few per compass sector, and every one of the 28
    that survived filtering was still inside 11 km. Each sector contributed
    its closest candidates, and the closest candidates to a city centre form a
    tight ring no matter which direction they lie in.

    So each sector is split into distance bands and drawn from evenly. A band
    yields its nearest member, which keeps the choice meaningful inside the
    band while making the pool cover the whole search area.
    """
    if not candidates or slots >= len(candidates):
        return list(candidates)

    buckets: dict[int, list[SpotCandidate]] = {}
    for candidate in candidates:
        buckets.setdefault(_bearing_sector(origin_gcj, candidate), []).append(candidate)

    # Bands are cut by *distance*, not by candidate count. Splitting the count
    # evenly fails on exactly the data this exists for: when 90% of candidates
    # sit within 10 km of the user, an equal-count fourth band still lands
    # inside those 10 km, and the pool never reaches the rest of a 150 km
    # radius. Measured on synthetic data shaped like the real one, count-bands
    # gave a pool topping out at 9.8 km out of 150.
    farthest = max(_candidate_distance_m(origin_gcj, candidate) for candidate in candidates)
    span = max(farthest, 1.0)
    bands = max(1, min(_POOL_DISTANCE_BANDS, math.ceil(slots / len(buckets))))
    ordered: list[SpotCandidate] = []
    for sector in sorted(buckets):
        bucket = buckets[sector]
        per_band, leftover = divmod(max(1, slots // len(buckets)), bands)
        for band_index in range(bands):
            if len(ordered) >= slots:
                break
            low = span * band_index / bands
            high = span * (band_index + 1) / bands
            band = [
                candidate
                for candidate in bucket
                if low <= _candidate_distance_m(origin_gcj, candidate) < high
                or (band_index == bands - 1 and
                    _candidate_distance_m(origin_gcj, candidate) >= low)
            ]
            if not band:
                continue
            take = per_band + (1 if band_index < leftover else 0)
            ordered.extend(band[:take])
    # Top up if the bands under-filled (a sector empty in some band), keeping
    # input order so the nearest candidates still serve as the fallback.
    if len(ordered) < slots:
        seen = {id(candidate) for candidate in ordered}
        for candidate in candidates:
            if len(ordered) >= slots:
                break
            if id(candidate) not in seen:
                ordered.append(candidate)
    return ordered[:slots]


def _interleave_sectors(
    origin_gcj: LatLon,
    candidates: list[SpotCandidate],
) -> list[SpotCandidate]:
    """Round-robin across distance rings *and* sectors.

    This decides which candidates get evaluated first, and that matters:
    evaluation stops as soon as enough qualify, so anything not measured is
    lost for good -- it has no drive estimate to be ranked by.

    Rotating over sectors alone is not enough. Each sector's queue is ordered
    by return time, so every sector's first entry is one of the nearest
    candidates; the first pass then returns eight spots in the same small
    ring. Rings must rotate too, otherwise the whole exercise only spreads the
    result by direction.

    Within a (ring, sector) cell, the caller's order is preserved, so the
    best-ranked candidate there still goes first.
    """
    if not candidates:
        return []
    farthest = max(_candidate_distance_m(origin_gcj, candidate) for candidate in candidates)
    span = max(farthest, 1.0)
    rings = _POOL_DISTANCE_BANDS

    cells: dict[tuple[int, int], list[SpotCandidate]] = {}
    for candidate in candidates:
        ring = min(
            rings - 1,
            int(_candidate_distance_m(origin_gcj, candidate) / span * rings),
        )
        cells.setdefault((ring, _bearing_sector(origin_gcj, candidate)), []).append(candidate)

    # Take one candidate per ring per pass, so the first pass already spans the
    # radius. Sectors rotate on a slower wheel than rings: with few slots, going
    # round the sectors first would spend the whole budget on the innermost
    # ring, which is exactly the clustering this is meant to avoid.
    ordered: list[SpotCandidate] = []
    pass_index = 0
    while len(ordered) < len(candidates):
        progressed = False
        for ring in range(rings):
            # One from each ring per pass, so the first pass alone spans the
            # whole radius. Draining a ring's sectors before starting the next
            # ring is what kept the head of the list inside the innermost band.
            sectors = sorted({s for r, s in cells if r == ring})
            if not sectors:
                continue
            # Rotate the sector per pass, so ring 0 does not always give up its
            # first direction.
            start = pass_index % len(sectors)
            for offset in range(len(sectors)):
                cell = cells[(ring, sectors[(start + offset) % len(sectors)])]
                if cell:
                    ordered.append(cell.pop(0))
                    progressed = True
                    break
        if not progressed:
            break
        pass_index += 1
    return ordered


def _separation_target_m(radius_m: float, limit: int) -> float:
    """How far apart two returned spots should ideally be.

    Scaled by the search radius, so a 5 km search is not expected to yield
    spots 20 km apart, and capped by what the radius can accommodate: asking
    for ``limit`` spots spread over a circle of radius R, the usable spacing is
    about 2R/limit. Taking the *minimum* of the two keeps a small search tight
    and a large one genuinely spread.
    """
    span = max(radius_m, 1.0)
    by_radius = span * _MIN_SEPARATION_RATIO
    by_budget = span * 2.0 / max(limit, 1)
    target = min(by_radius, by_budget)
    return max(_MIN_SEPARATION_FLOOR_M, min(_MIN_SEPARATION_CEIL_M, target))


def _water_key_text(name: str) -> str:
    """Name with the usual AMap decorations stripped.

    AMap lists one river as several POIs -- "府河", "府河(锦江)", "锦江" are the
    same water body, and a page showing three cards that all say 府河 gives the
    user no choice to make. Parentheticals carry a district or a road rather
    than a different river, so they are dropped for comparison.
    """
    text = name or ""
    for opener, closer in (("(", ")"), ("（", "）")):
        while opener in text and closer in text:
            start = text.index(opener)
            end = text.index(closer, start)
            text = text[:start] + text[end + 1 :]
    return text.replace(" ", "").strip()


def _collapse_duplicate_candidates(
    candidates: list[SpotCandidate],
) -> list[SpotCandidate]:
    """Same dedup, applied to the pool *before* any drive estimate is spent.

    Doing it only after evaluation wastes budget measuring the same river three
    times and then throws two of those measurements away -- and because
    evaluation stops once enough candidates qualify, the duplicates can also
    eat the slots that a distinct water needed.
    """
    seen: set[str] = set()
    kept: list[SpotCandidate] = []
    for candidate in candidates:
        key = _water_key_text(candidate.name)
        if key in seen:
            continue
        seen.add(key)
        kept.append(candidate)
    return kept


def _min_pairwise_distance(spots: list[SpotOut]) -> float:
    """Smallest gap between any two of these spots; 0 when fewer than two."""
    smallest = math.inf
    for index, spot in enumerate(spots):
        for other in spots[index + 1 :]:
            smallest = min(
                smallest,
                haversine_m(
                    spot.location_gcj02.lat,
                    spot.location_gcj02.lon,
                    other.location_gcj02.lat,
                    other.location_gcj02.lon,
                ),
            )
    return smallest if math.isfinite(smallest) else 0.0


def _interleave_by_spacing(
    spots: list[SpotOut],
    target_separation_m: float,
) -> tuple[list[SpotOut], bool]:
    """Reorder a ranked list so consecutive picks are far apart.

    Greedy: take the best remaining spot that clears the target from everything
    already taken, and halve the target when nothing does. Every spot is kept --
    this only changes the order, so paging never loses a candidate and page 2
    cannot repeat one from page 1.

    Ordering by this rule is what makes a page spread out: page 1 is the first
    ``limit`` picks of the interleaved sequence, so it alternates between the
    different parts of the search area instead of draining the top-ranked
    cluster first.
    """
    remaining = sorted(
        spots, key=lambda s: (-s.total_score, s.drive_seconds_round_trip, s.id)
    )
    ordered: list[SpotOut] = []
    relaxed = False
    separation = float(target_separation_m)
    while remaining:
        if not ordered:
            # Nothing to be far from yet, so the best candidate goes first.
            ordered.append(remaining.pop(0))
            continue

        picked_index = next(
            (
                index
                for index, spot in enumerate(remaining)
                if min(
                    haversine_m(
                        spot.location_gcj02.lat,
                        spot.location_gcj02.lon,
                        other.location_gcj02.lat,
                        other.location_gcj02.lon,
                    )
                    for other in ordered
                )
                >= separation
            ),
            None,
        )
        if picked_index is None:
            # Nothing clears the bar. Halve it and look again -- falling through
            # to pop(None) here is what would crash. Once the bar is under a
            # metre the best remaining is accepted, because every candidate must
            # still appear or paging would silently drop spots.
            relaxed = True
            separation /= 2.0
            if separation < 1.0:
                separation = 0.0
                ordered.append(remaining.pop(0))
            continue
        ordered.append(remaining.pop(picked_index))
    return ordered, relaxed


async def _evaluate_candidate(
    provider: GeoProvider,
    origin: LatLon,
    candidate: SpotCandidate,
    departure: datetime,
    semaphore: asyncio.Semaphore,
    *,
    origin_gcj: LatLon,
    fish_score: int,
    fish_band: str,
) -> SpotOut | str:
    entry = candidate.entry_location_gcj02 or candidate.location_gcj02

    # The live AMap provider ignores ``direction``: out and back issue identical
    # requests to the same origin/destination, so asking twice doubled both the
    # quota cost and — at the account's hard 2 QPS ceiling — the latency, for
    # nothing. Providers whose result actually depends on ``direction`` (the
    # mock does) opt out by setting ``direction_affects_result = True``;
    # ``getattr`` keeps lightweight test doubles working unchanged.
    if getattr(provider, "direction_affects_result", False):
        directions = ("out", "back")
    else:
        directions = ("out",)
    results = []
    for direction in directions:
        async with semaphore:
            try:
                results.append(
                    await _drive_seconds(
                        provider, origin, entry, departure, direction, candidate.id
                    )
                )
            except UpstreamQuotaExceeded:
                # Quota exhaustion must abort the request as 429, not look like
                # a single unavailable candidate.
                raise
            except Exception as exc:  # noqa: BLE001 - one spot must not sink the batch
                logger.warning("drive estimate failed for %s: %s", candidate.id, exc)
                return "unavailable"
    out_seconds = results[0]
    back_seconds = results[-1]
    if out_seconds <= 0 or back_seconds <= 0:
        return "over_two_hours"
    if out_seconds + back_seconds > ROUND_TRIP_LIMIT_SECONDS:
        return "over_two_hours"
    return _build_spot(
        candidate,
        origin_gcj=origin_gcj,
        out_seconds=out_seconds,
        back_seconds=back_seconds,
        fish_score=fish_score,
        fish_band=fish_band,
    )


async def build_spot_recommendations(
    geo_provider: GeoProvider,
    weather_provider: WeatherProvider,
    *,
    lat: float,
    lon: float,
    radius_km: float,
    limit: int,
    species: str | None,
    offset: int = 0,
    min_radius_km: float = 0.0,
) -> SpotRecommendationResponse:
    normalized_species = validate_species(species)
    cache_key = _spot_cache_key(
        lat=lat,
        lon=lon,
        min_radius_km=min_radius_km,
        radius_km=radius_km,
        limit=limit,
        species=normalized_species,
        offset=offset,
    )
    cached = _read_spot_cache(cache_key, time.monotonic())
    if cached is not None:
        logger.info("spot recommendation cache hit (%.0f ms budget)", _CACHE_TTL_SECONDS * 1000)
        return cached

    origin = LatLon(lat=lat, lon=lon)
    origin_gcj_coord = wgs84_to_gcj02(lat, lon)
    origin_gcj = LatLon(lat=origin_gcj_coord.lat, lon=origin_gcj_coord.lon)
    radius_m = radius_km * 1000.0

    settings = get_settings()
    semaphore = asyncio.Semaphore(settings.amap_concurrency)
    candidates = await _recall(geo_provider, origin, radius_m, semaphore)

    departure = datetime.now(timezone.utc)
    base_score, base_band = await _baseline_fish_score(
        weather_provider, lat, lon, departure, normalized_species
    )

    # A ring search, not just a cap: "10~50 km" means the near field is excluded
    # too. Done first, so every counter below describes the ring rather than the
    # whole circle -- otherwise ``forbidden`` would include spots the user ruled
    # out by distance and the filtered invariants would not add up.
    if min_radius_km > 0:
        min_radius_m = min_radius_km * 1000.0
        in_ring = [
            candidate
            for candidate in candidates
            if _candidate_distance_m(origin_gcj, candidate) >= min_radius_m
        ]
        min_ring_skipped = len(candidates) - len(in_ring)
    else:
        in_ring = candidates
        min_ring_skipped = 0

    forbidden = 0
    evaluable: list[SpotCandidate] = []
    for candidate in in_ring:
        if forbidden_reason(candidate.name, candidate.location_gcj02):
            forbidden += 1
            continue
        evaluable.append(candidate)
    evaluable.sort(
        key=lambda candidate: (_candidate_distance_m(origin_gcj, candidate), candidate.id)
    )
    # One entry per distinct water before spending anything on drive estimates.
    # AMap returns a river as several POIs; measuring all of them costs quota
    # and latency to learn the same answer, and the duplicates then compete
    # with the distinct waters for the page.
    distinct_pool = _collapse_duplicate_candidates(evaluable)
    duplicate_count = len(evaluable) - len(distinct_pool)
    if distinct_pool:
        evaluable = distinct_pool
    # Report against everything that survived filtering, before the pool narrows
    # it. The field means "candidates we did not evaluate", and the reader's
    # question is how much of the search was skipped. Duplicates are folded in
    # here rather than tracked as a fourth bucket: they were recalled but never
    # evaluated, which is exactly what ``unevaluated`` counts.
    total_evaluable = len(evaluable) + duplicate_count
    # Build the evaluation pool from every direction and every distance ring,
    # not just the nearest candidates.
    #
    # The pool is deliberately small. A wide pool looks like the obvious answer
    # and is not: measured from Chengdu at a 150 km radius, spreading 40
    # candidates across the radius and evaluating 30 cost three times the drive
    # calls of the old code and returned *fewer* spots (8 instead of 10),
    # because most of the far ring fails the two-hour round trip. Paying three
    # times as much to show less is not a trade worth making. A pool of
    # ``limit + 4`` keeps the cost near the old one while still letting the
    # batch come from different places.
    # The pool must stay deep. Shrinking it to ``limit + slack`` looked cheaper
    # and returned fewer spots: with candidates that are good but scattered,
    # a shallow pool never reaches them, so a case that used to fill five cards
    # came back with two. Depth is also what makes the spread meaningful.
    wanted = max(_POOL_FLOOR, offset + limit + _POOL_SLACK)
    batch = max(limit, _MIN_EVALUATION_BATCH)
    pool_size = min(
        len(evaluable),
        math.ceil(wanted / batch) * batch,
    )
    evaluable = _sector_balanced_pool(origin_gcj, evaluable, pool_size)
    evaluable = await _order_by_batch_return(geo_provider, origin, evaluable)
    # Then interleave, so the batch actually spans the pool instead of draining
    # its nearest edge. Evaluation stops once enough candidates qualify, and a
    # candidate that is never measured cannot be brought back later -- it has
    # no drive estimate to rank with.
    evaluable = _interleave_sectors(origin_gcj, evaluable)

    target_eligible = offset + limit
    batch_size = max(limit, _MIN_EVALUATION_BATCH)
    # The cap follows the pool: the pool is what was chosen to be worth
    # measuring, so it is also what the budget allows.
    evaluation_cap = min(len(evaluable), max(target_eligible, len(evaluable)))
    evaluated = 0
    unavailable = 0
    over_two_hours = 0
    eligible: list[SpotOut] = []
    for start in range(0, evaluation_cap, batch_size):
        batch = evaluable[start : min(start + batch_size, evaluation_cap)]
        results = await asyncio.gather(
            *(
                _evaluate_candidate(
                    geo_provider,
                    origin,
                    candidate,
                    departure,
                    semaphore,
                    origin_gcj=origin_gcj,
                    fish_score=min(100, base_score + (3 if candidate.downwind else 0)),
                    fish_band=base_band,
                )
                for candidate in batch
            )
        )
        evaluated += len(batch)
        for result in results:
            if isinstance(result, SpotOut):
                eligible.append(result)
            elif result == "unavailable":
                unavailable += 1
            else:
                over_two_hours += 1
        if len(eligible) >= target_eligible:
            break

    unevaluated = total_evaluable - evaluated
    eligible.sort(key=lambda spot: (-spot.total_score, spot.drive_seconds_round_trip, spot.id))
    # Spreading has to see the whole ranked set, not one page: cutting it to a
    # page-sized pool first would leave the same near-neighbours, and paging
    # after that could still repeat a spot across pages. Interleaving the full
    # set and then slicing keeps pages disjoint and every page spread alike.
    target_gap = _separation_target_m(radius_m, limit)
    spread, relaxed = _interleave_by_spacing(eligible, target_gap)
    # Spreading decides *which* spots come back and in what order they are
    # paged, but the list shown to the user stays ranked best-first -- that is
    # what the card order promises, and the previous contract guaranteed it.
    returned = spread[offset : offset + limit]
    returned.sort(key=lambda spot: (-spot.total_score, spot.drive_seconds_round_trip, spot.id))
    # Report the gap this page actually achieves -- that is the number a reader
    # checking "is this really spread out?" wants, not the target we aimed for.
    separation_m = _min_pairwise_distance(returned)

    response = SpotRecommendationResponse(
        user_location=UserLocationOut(
            wgs84=origin,
            gcj02=LatLon(lat=origin_gcj_coord.lat, lon=origin_gcj_coord.lon),
        ),
        spots=returned,
        filtered=FilteredStats(
            total_candidates=len(candidates),
            within_min_radius=min_ring_skipped,
            forbidden=forbidden,
            unavailable=unavailable,
            over_two_hours=over_two_hours,
            eligible=len(eligible),
            returned=len(returned),
            truncated_by_limit=len(eligible) - len(returned),
            evaluated=evaluated,
            unevaluated=unevaluated,
        ),
        meta=SpotsMeta(
            mock_mode=settings.mock_mode,
            min_radius_km=min_radius_km,
            radius_km=radius_km,
            round_trip_limit_seconds=ROUND_TRIP_LIMIT_SECONDS,
            traffic_basis=TRAFFIC_BASIS,
            generated_at=utc_timestamp(),
            selection_strategy=_SELECTION_STRATEGY,
            min_separation_m=int(round(separation_m)),
            separation_relaxed=relaxed,
        ),
    )
    _write_spot_cache(cache_key, response, time.monotonic())
    return response
