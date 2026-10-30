"""Provider protocols. Tests inject fakes through FastAPI dependency overrides."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from fishagent.schemas import (
    LatLon,
    PlaceCandidate,
    SpotCandidate,
    SpotSpeciesQuery,
    WeatherSnapshot,
)


class ProviderError(RuntimeError):
    """Raised when an upstream provider cannot return usable data."""


class UpstreamQuotaExceeded(RuntimeError):
    """Raised before an upstream call that would exceed the daily quota.

    Deliberately not a ProviderError: services treat ProviderError as a partial
    failure (skip shard / fall back), while quota exhaustion must abort the
    request and surface as HTTP 429.

    Exception: the species endpoint (contract 4.6) degrades every provider
    failure, including quota exhaustion, to HTTP 200 with ``degraded=true``.
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
    """Water POI lookup, driving times, and location-picker helpers.

    ``search_places`` and ``nearby_water`` back the Step 1 location picker: most
    anglers know a place by name, not by coordinates. They are part of this
    protocol rather than a separate one because they hit the same upstream, the
    same key and the same quota; a provider that cannot resolve a name cannot
    offer a picker but can still recommend spots, so both are optional at the
    call site (guarded with ``getattr``).
    """

    async def find_water_spots(
        self,
        origin: LatLon,
        center: LatLon,
        radius_m: int,
    ) -> list[SpotCandidate]: ...

    async def search_places(self, keyword: str, *, limit: int = 8) -> list[PlaceCandidate]:
        ...

    async def nearby_water(
        self, origin: LatLon, *, radius_m: int = 30_000, limit: int = 8
    ) -> list[PlaceCandidate]: ...

    async def estimate_drive_seconds(
        self,
        origin: LatLon,
        destination: LatLon,
        departure_at: datetime,
        direction: str,
        route_key: str = "",
    ) -> int: ...


@runtime_checkable
class SpeciesProvider(Protocol):
    """Community-backed fish-species lookup.

    A real Xiaohongshu adapter implements this protocol and returns one raw
    species list per input spot, in the same order. An empty list means the
    water body has no usable community recommendation.

    ``resolves_empty`` distinguishes "I looked and found nothing" (True, the
    default) from "I never look" (False, e.g. the null provider). Only the
    former justifies a water-type fallback: for the latter the empty list is a
    configuration choice, and inventing species would misrepresent it.
    """

    name: str
    resolves_empty: bool
    source_label: str
    # Optional presentation metadata. When omitted the service falls back to the
    # Xiaohongshu wording so existing adapters keep their contract.
    source_key: str
    found_note: str
    source_disclosure: str

    async def find_species(
        self,
        spots: list[SpotSpeciesQuery],
    ) -> list[list[str]]: ...
