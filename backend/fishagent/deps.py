"""FastAPI dependency seams for weather and geo providers.

Tests override these exact callables with `app.dependency_overrides` to inject
fake providers (radius spies, round-trip fixtures, missing entry coordinates).
"""

from __future__ import annotations

from fishagent.config import get_settings
from fishagent.errors import ApiError
from fishagent.pilot import get_pilot_state
from fishagent.pilot.limits import QuotaGuardedGeoProvider, QuotaGuardedWeatherProvider
from fishagent.providers.amap import AMapGeoProvider
from fishagent.providers.amap_mock import MockGeoProvider
from fishagent.providers.base import GeoProvider, WeatherProvider
from fishagent.providers.open_meteo import OpenMeteoWeatherProvider
from fishagent.providers.weather_mock import MockWeatherProvider


def get_weather_provider() -> WeatherProvider:
    settings = get_settings()
    if settings.mock_mode:
        return MockWeatherProvider()
    provider = OpenMeteoWeatherProvider(base_url=settings.open_meteo_base_url)
    pilot_state = get_pilot_state(settings)
    if pilot_state is None:
        return provider
    return QuotaGuardedWeatherProvider(provider, pilot_state.ledger)


def get_geo_provider() -> GeoProvider:
    settings = get_settings()
    if settings.mock_mode:
        return MockGeoProvider()
    if not settings.amap_web_key:
        raise ApiError(
            status_code=503,
            code="PROVIDER_NOT_CONFIGURED",
            message="未配置 AMAP_WEB_KEY，无法调用真实钓位数据源",
        )
    provider = AMapGeoProvider(api_key=settings.amap_web_key, qps=settings.amap_qps)
    pilot_state = get_pilot_state(settings)
    if pilot_state is None:
        return provider
    return QuotaGuardedGeoProvider(provider, pilot_state.ledger)
