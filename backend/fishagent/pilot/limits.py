"""In-process rate limiting and daily upstream quotas for the pilot deployment.

Single-process only: counters live in memory and reset on restart. The pilot
runs one uvicorn worker; multi-worker deployments need a shared store (Redis)
and are explicitly out of scope for CR-03 M2.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fishagent.providers.base import (
    GeoProvider,
    UpstreamQuotaExceeded,
    WeatherProvider,
)
from fishagent.schemas import LatLon, SpotCandidate, WeatherSnapshot

logger = logging.getLogger(__name__)

QUOTA_PROVIDERS = ("amap", "open_meteo", "llm")
_MAX_RATE_KEYS = 20_000


class SlidingWindowLimiter:
    """Per-key sliding window; returns a Retry-After value instead of raising."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int | None:
        """Record one hit. Returns None when allowed, else seconds to wait."""
        with self._lock:
            now = self.clock()
            cutoff = now - self.window_seconds
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= _MAX_RATE_KEYS:
                    self._prune(cutoff)
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return max(1, math.ceil(bucket[0] + self.window_seconds - now))
            bucket.append(now)
            return None

    def _prune(self, cutoff: float) -> None:
        stale = [key for key, bucket in self._buckets.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            del self._buckets[key]

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class DailyQuotaLedger:
    """Counts real upstream calls per provider per local calendar day."""

    def __init__(
        self,
        limits: dict[str, int],
        day_timezone: str = "Asia/Shanghai",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        missing = [name for name in QUOTA_PROVIDERS if name not in limits]
        if missing:
            raise ValueError(f"missing quota limits for: {', '.join(missing)}")
        self._limits = {name: int(limits[name]) for name in QUOTA_PROVIDERS}
        self._timezone = ZoneInfo(day_timezone)
        self.timezone_name = day_timezone
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._day = self._current_day()
        self._used = {name: 0 for name in QUOTA_PROVIDERS}
        self._exhausted: set[str] = set()

    def _current_day(self) -> str:
        return self._clock().astimezone(self._timezone).date().isoformat()

    def _rollover(self) -> None:
        today = self._current_day()
        if today != self._day:
            self._day = today
            self._used = {name: 0 for name in QUOTA_PROVIDERS}
            self._exhausted.clear()

    def check_available(self, provider: str) -> None:
        with self._lock:
            self._rollover()
            self._check_locked(provider)

    def _check_locked(self, provider: str) -> None:
        limit = self._limits[provider]
        if provider in self._exhausted or self._used[provider] >= limit:
            self._exhausted.add(provider)
            raise UpstreamQuotaExceeded(provider, self._retry_after_locked())

    def consume(self, provider: str, units: int = 1) -> None:
        if units <= 0:
            return
        with self._lock:
            self._rollover()
            limit = self._limits[provider]
            if provider in self._exhausted or self._used[provider] + units > limit:
                self._exhausted.add(provider)
                logger.warning(
                    "daily upstream quota exhausted provider=%s used=%d limit=%d day=%s",
                    provider,
                    self._used[provider],
                    limit,
                    self._day,
                )
                raise UpstreamQuotaExceeded(provider, self._retry_after_locked())
            self._used[provider] += units

    def _retry_after_locked(self) -> int:
        local_now = self._clock().astimezone(self._timezone)
        tomorrow = (local_now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return max(1, int((tomorrow - local_now).total_seconds()))

    def retry_after_seconds(self) -> int:
        with self._lock:
            return self._retry_after_locked()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._rollover()
            return {
                "day": self._day,
                "timezone": self.timezone_name,
                "providers": {
                    name: {
                        "used": self._used[name],
                        "limit": self._limits[name],
                        "remaining": max(0, self._limits[name] - self._used[name]),
                        "exhausted": name in self._exhausted,
                    }
                    for name in QUOTA_PROVIDERS
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._day = self._current_day()
            self._used = {name: 0 for name in QUOTA_PROVIDERS}
            self._exhausted.clear()


class QuotaGuardedGeoProvider:
    """Wraps the real AMap adapter; each upstream call consumes one daily unit."""

    def __init__(self, inner: GeoProvider, ledger: DailyQuotaLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    async def find_water_spots(
        self,
        origin: LatLon,
        center: LatLon,
        radius_m: int,
    ) -> list[SpotCandidate]:
        self._ledger.consume("amap")
        return await self._inner.find_water_spots(origin, center, radius_m)

    async def estimate_drive_seconds(
        self,
        origin: LatLon,
        destination: LatLon,
        departure_at: datetime,
        direction: str,
        route_key: str = "",
    ) -> int:
        self._ledger.consume("amap")
        return await self._inner.estimate_drive_seconds(
            origin, destination, departure_at, direction, route_key
        )

    async def estimate_batch_drive_seconds(
        self,
        origin: LatLon,
        destinations: list[LatLon],
    ) -> list[int | None]:
        self._ledger.consume("amap")
        return await self._inner.estimate_batch_drive_seconds(origin, destinations)


class QuotaGuardedWeatherProvider:
    """Wraps the real Open-Meteo adapter; one forecast call = one daily unit."""

    def __init__(self, inner: WeatherProvider, ledger: DailyQuotaLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    async def get_weather(
        self,
        lat: float,
        lon: float,
        at: datetime,
        scenario: str | None = None,
    ) -> WeatherSnapshot:
        self._ledger.consume("open_meteo")
        return await self._inner.get_weather(lat, lon, at, scenario)
