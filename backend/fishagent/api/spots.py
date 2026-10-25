"""GET /api/spots/recommend."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from fishagent.deps import get_geo_provider, get_weather_provider
from fishagent.providers.base import GeoProvider, WeatherProvider
from fishagent.schemas import SpotRecommendationResponse
from fishagent.services import spots as spot_service

router = APIRouter(prefix="/api", tags=["spots"])


@router.get("/spots/recommend", response_model=SpotRecommendationResponse)
async def recommend_spots(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    species: str | None = Query(default=None),
    radius_km: float = Query(default=100, ge=1, le=150),
    limit: int = Query(default=5, ge=1, le=10),
    offset: int = Query(default=0, ge=0, le=20),
    geo_provider: GeoProvider = Depends(get_geo_provider),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
) -> SpotRecommendationResponse:
    return await spot_service.build_spot_recommendations(
        geo_provider,
        weather_provider,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        limit=limit,
        offset=offset,
        species=species,
    )
