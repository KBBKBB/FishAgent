"""Provider protocols. Tests inject fakes through FastAPI dependency overrides."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from fishagent.schemas import LatLon, SpotCandidate, WeatherSnapshot


class ProviderError(RuntimeError):
    """Raised when an upstream provider cannot return usable data."""


class UpstreamQuotaExceeded(RuntimeError):
    """Raised before an upstream call that would exceed the daily quota.

    Deliberately not a ProviderError: services treat ProviderError as a partial
    failure (skip shard / fall back), while quota exhaustion must abort the
    request and surface as HTTP 429.
    """

    def __init__(self, provider: str, retry_after_seconds: int) -> None:
        super().__init__(f"daily quota exhausted for {provider}")
        self.provider = provider
        self.retry_after_seconds = max(1, int(retry_after_seconds))


@runtime_checkable
class WeatherProvider(Protocol):
    async def get_weather(
        self,
        lat: float,
        lon: float,
        at: datetime,
        scenario: str | None = None,
    ) -> WeatherSnapshot: ...


@runtime_checkable
class GeoProvider(Protocol):
    async def find_water_spots(
        self,
        origin: LatLon,
        center: LatLon,
        radius_m: int,
    ) -> list[SpotCandidate]: ...

    async def estimate_drive_seconds(
        self,
        origin: LatLon,
        destination: LatLon,
        departure_at: datetime,
        direction: str,
        route_key: str = "",
    ) -> int: ...
