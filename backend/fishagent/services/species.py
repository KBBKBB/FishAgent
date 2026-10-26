"""Community species lookup: provider call, short-lived cache, graceful fallback."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

from fishagent.config import get_settings
from fishagent.core.species import normalize_species
from fishagent.providers.base import SpeciesProvider
from fishagent.schemas import (
    SpeciesRecommendationResponse,
    SpotSpeciesQuery,
    SpotSpeciesResult,
)
from fishagent.services.fish_activity import utc_timestamp

logger = logging.getLogger(__name__)

SOURCE_DISCLOSURE = (
    "鱼种信息来自小红书网友分享，仅供参考，不承诺渔获；请出发前自行核实。"
)
FOUND_NOTE = "来自小红书网友分享，仅供参考"
EMPTY_NOTE = "暂无相关鱼种推荐"
# Providers may override presentation; these match the Xiaohongshu contract.
_DEFAULT_SOURCE_KEY = "xiaohongshu"
_EMPTY_CACHE_TTL_SECONDS = 300
_MAX_CACHE_ENTRIES = 2_000

# Cache keys are tuples so names containing the old "|" separator can never
# collide with a different (name, water_type) pair.
CacheKey = tuple[str, str]


@dataclass
class _CacheEntry:
    species: list[str]
    expires_at: float
    degraded: bool = False


_cache: dict[CacheKey, _CacheEntry] = {}
_cache_lock = threading.Lock()


def reset_species_cache() -> None:
    """Test/ops hook: drop cached community lookups."""
    with _cache_lock:
        _cache.clear()


def _normalise_part(value: str) -> str:
    """Same normalisation for cache reads and writes, so keys always match."""
    return value.strip()


def _cache_key(spot: SpotSpeciesQuery) -> CacheKey:
    return (_normalise_part(spot.name), _normalise_part(spot.water_type))


def _read_cache(key: CacheKey, now: float) -> tuple[list[str], bool] | None:
    """Return (species, degraded) for a live entry, or None on a miss."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            _cache.pop(key, None)
            return None
        return list(entry.species), entry.degraded


def _write_cache(
    key: CacheKey,
    species: list[str],
    ttl: int,
    *,
    degraded: bool = False,
) -> None:
    if ttl <= 0:
        return
    # Contract 4.6: empty lookups and degraded fallbacks are cached for at most
    # five minutes; only successful, non-empty results use the full TTL.
    if degraded or not species:
        effective_ttl = min(ttl, _EMPTY_CACHE_TTL_SECONDS)
    else:
        effective_ttl = ttl
    with _cache_lock:
        if len(_cache) >= _MAX_CACHE_ENTRIES:
            now = time.monotonic()
            for item in [k for k, entry in _cache.items() if entry.expires_at <= now]:
                _cache.pop(item, None)
            if len(_cache) >= _MAX_CACHE_ENTRIES:
                _cache.clear()
        _cache[key] = _CacheEntry(
            species=list(species),
            expires_at=time.monotonic() + effective_ttl,
            degraded=degraded,
        )


def _cache_degraded(
    misses: list[tuple[CacheKey, SpotSpeciesQuery]],
    ttl: int,
) -> None:
    """Negative-cache a failed batch so an outage does not hammer upstream."""
    for key, _ in misses:
        _write_cache(key, [], ttl, degraded=True)


async def _lookup(
    provider: SpeciesProvider,
    unique: dict[CacheKey, SpotSpeciesQuery],
    cache_ttl_seconds: int,
) -> tuple[dict[CacheKey, list[str]], bool]:
    """Return species per cache key plus a `degraded` flag.

    Contract 4.6: a provider timeout, exception or malformed payload degrades
    the whole response. When degraded, the returned mapping is empty so callers
    cannot mix cached values into an all-empty fallback.
    """
    resolved: dict[CacheKey, list[str]] = {}
    misses: list[tuple[CacheKey, SpotSpeciesQuery]] = []
    cached_degraded = False
    if cache_ttl_seconds <= 0:
        # TTL=0 disables the cache entirely: neither read nor write.
        misses = list(unique.items())
    else:
        now = time.monotonic()
        for key, spot in unique.items():
            cached = _read_cache(key, now)
            if cached is not None:
                species, degraded = cached
                resolved[key] = species
                cached_degraded = cached_degraded or degraded
            else:
                misses.append((key, spot))

    if not misses:
        if cached_degraded:
            return {}, True
        return resolved, False

    settings = get_settings()
    try:
        raw = await asyncio.wait_for(
            provider.find_species([spot for _, spot in misses]),
            timeout=settings.species_timeout_seconds,
        )
    except asyncio.CancelledError:
        # Never turn cancellation into a degraded 200 response.
        raise
    except asyncio.TimeoutError:
        logger.warning(
            "species provider timed out after %.1fs",
            settings.species_timeout_seconds,
        )
        _cache_degraded(misses, cache_ttl_seconds)
        return {}, True
    except Exception:
        # Includes UpstreamQuotaExceeded: contract 4.6 has no quota/429 carve-out
        # for this endpoint and requires degradation, never a 5xx.
        logger.warning("species provider failed", exc_info=True)
        _cache_degraded(misses, cache_ttl_seconds)
        return {}, True

    if not isinstance(raw, list) or len(raw) != len(misses):
        logger.warning(
            "species provider returned an unexpected payload (%s rows for %d spots)",
            len(raw) if isinstance(raw, list) else type(raw).__name__,
            len(misses),
        )
        _cache_degraded(misses, cache_ttl_seconds)
        return {}, True

    malformed = next(
        (index for index, row in enumerate(raw) if not isinstance(row, (list, tuple))),
        None,
    )
    if malformed is not None:
        logger.warning(
            "species provider returned a malformed row at index %d (%s)",
            malformed,
            type(raw[malformed]).__name__,
        )
        _cache_degraded(misses, cache_ttl_seconds)
        return {}, True

    for (key, _), values in zip(misses, raw):
        species = normalize_species(values)
        resolved[key] = species
        _write_cache(key, species, cache_ttl_seconds)

    if cached_degraded:
        # A previously degraded entry keeps the whole response degraded so
        # callers never see a 200 that mixes cached positives with failures.
        return {}, True
    return resolved, False


async def build_species_recommendations(
    provider: SpeciesProvider,
    spots: list[SpotSpeciesQuery],
) -> SpeciesRecommendationResponse:
    settings = get_settings()
    keys = [_cache_key(spot) for spot in spots]
    unique: dict[CacheKey, SpotSpeciesQuery] = {}
    for key, spot in zip(keys, spots):
        unique.setdefault(key, spot)

    resolved, degraded = await _lookup(
        provider,
        unique,
        settings.species_cache_ttl_seconds,
    )

    # Providers declare their own presentation; fall back to the Xiaohongshu
    # wording so older adapters keep working unchanged.
    source_key = getattr(provider, "source_key", _DEFAULT_SOURCE_KEY) or _DEFAULT_SOURCE_KEY
    found_note = getattr(provider, "found_note", FOUND_NOTE) or FOUND_NOTE
    disclosure = getattr(provider, "source_disclosure", SOURCE_DISCLOSURE) or SOURCE_DISCLOSURE

    results: list[SpotSpeciesResult] = []
    for spot, key in zip(spots, keys):
        # Degraded responses are all-empty by contract: never surface cache hits.
        species = [] if degraded else resolved.get(key, [])
        has_recommendation = bool(species)
        results.append(
            SpotSpeciesResult(
                spot_id=spot.spot_id,
                spot_name=spot.name,
                species=species,
                has_recommendation=has_recommendation,
                source=source_key if has_recommendation else "none",
                source_label=provider.source_label if has_recommendation else "",
                note=found_note if has_recommendation else EMPTY_NOTE,
            )
        )

    return SpeciesRecommendationResponse(
        results=results,
        provider=provider.name,
        degraded=degraded,
        source_disclosure=disclosure,
        generated_at=utc_timestamp(),
    )
