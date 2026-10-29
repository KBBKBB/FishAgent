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
    *, lat: float, lon: float, radius_km: float, limit: int, species: str | None, offset: int
) -> tuple:
    # Coordinates are rounded to ~100 m so trivial GPS jitter still hits the
    # cache; anything finer would produce a new key per request and never hit.
    return (
        round(lat, 3),
        round(lon, 3),
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
) -> SpotRecommendationResponse:
    normalized_species = validate_species(species)
    cache_key = _spot_cache_key(
        lat=lat,
        lon=lon,
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

    forbidden = 0
    evaluable: list[SpotCandidate] = []
    for candidate in candidates:
        if forbidden_reason(candidate.name, candidate.location_gcj02):
            forbidden += 1
            continue
        evaluable.append(candidate)
    evaluable.sort(
        key=lambda candidate: (_candidate_distance_m(origin_gcj, candidate), candidate.id)
    )
    evaluable = await _order_by_batch_return(geo_provider, origin, evaluable)

    target_eligible = offset + limit
    batch_size = max(limit, _MIN_EVALUATION_BATCH)
    evaluation_cap = min(len(evaluable), _MAX_EVALUATED_CANDIDATES)
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

    unevaluated = len(evaluable) - evaluated
    eligible.sort(key=lambda spot: (-spot.total_score, spot.drive_seconds_round_trip, spot.id))
    returned = eligible[offset : offset + limit]

    response = SpotRecommendationResponse(
        user_location=UserLocationOut(
            wgs84=origin,
            gcj02=LatLon(lat=origin_gcj_coord.lat, lon=origin_gcj_coord.lon),
        ),
        spots=returned,
        filtered=FilteredStats(
            total_candidates=len(candidates),
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
            radius_km=radius_km,
            round_trip_limit_seconds=ROUND_TRIP_LIMIT_SECONDS,
            traffic_basis=TRAFFIC_BASIS,
            generated_at=utc_timestamp(),
        ),
    )
    _write_spot_cache(cache_key, response, time.monotonic())
    return response
