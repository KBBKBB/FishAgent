"""GET /api/spots/recommend."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from fishagent.deps import get_geo_provider, get_weather_provider
from fishagent.errors import ApiError
from fishagent.providers.base import GeoProvider, WeatherProvider
from fishagent.schemas import SpotRecommendationResponse
from fishagent.services import spots as spot_service

router = APIRouter(prefix="/api", tags=["spots"])


@router.get("/spots/recommend", response_model=SpotRecommendationResponse)
async def recommend_spots(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    species: str | None = Query(default=None),
    min_radius_km: float = Query(default=0, ge=0, le=150),
    radius_km: float = Query(default=100, ge=1, le=150),
    limit: int = Query(default=5, ge=1, le=10),
    offset: int = Query(default=0, ge=0, le=20),
    geo_provider: GeoProvider = Depends(get_geo_provider),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
) -> SpotRecommendationResponse:
    """``radius_km`` is the outer edge, ``min_radius_km`` the inner one.

    The pair is a ring: "10~50km" means exclude anything nearer than 10 km as
    well as anything beyond 50. ``min_radius_km`` defaults to 0, so the old
    single-radius call keeps working unchanged.
    """
    if min_radius_km >= radius_km:
        raise ApiError(
            status_code=422,
            code="INVALID_RADIUS_RANGE",
            message=f"搜索区间的起点必须小于终点：{min_radius_km:g}~{radius_km:g} km",
        )
    return await spot_service.build_spot_recommendations(
        geo_provider,
        weather_provider,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        min_radius_km=min_radius_km,
        limit=limit,
        offset=offset,
        species=species,
    )
