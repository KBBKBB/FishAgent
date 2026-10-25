"""GET /api/fish-activity."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from fishagent.deps import get_weather_provider
from fishagent.providers.base import WeatherProvider
from fishagent.schemas import FishActivityResponse
from fishagent.services import fish_activity as fish_service

Scenario = Literal["excellent", "good", "fair", "poor", "no_go"]

router = APIRouter(prefix="/api", tags=["fish-activity"])


@router.get("/fish-activity", response_model=FishActivityResponse)
async def get_fish_activity(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    at: str | None = Query(default=None),
    scenario: Scenario | None = Query(default=None),
    species: str | None = Query(default=None),
    provider: WeatherProvider = Depends(get_weather_provider),
) -> FishActivityResponse:
    return await fish_service.build_fish_activity(
        provider,
        lat=lat,
        lon=lon,
        at=at,
        scenario=scenario,
        species=species,
    )
