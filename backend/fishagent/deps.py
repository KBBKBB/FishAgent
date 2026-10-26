"""FastAPI dependency seams for weather and geo providers.

Tests override these exact callables with `app.dependency_overrides` to inject
fake providers (radius spies, round-trip fixtures, missing entry coordinates).
"""

from __future__ import annotations

import logging

from fishagent.agent.llm import load_llm_settings
from fishagent.config import get_settings
from fishagent.errors import ApiError
from fishagent.pilot import get_pilot_state
from fishagent.pilot.limits import QuotaGuardedGeoProvider, QuotaGuardedWeatherProvider
from fishagent.providers.amap import AMapGeoProvider
from fishagent.providers.amap_mock import MockGeoProvider
from fishagent.providers.base import GeoProvider, SpeciesProvider, WeatherProvider
from fishagent.providers.open_meteo import OpenMeteoWeatherProvider
from fishagent.providers.species_bing import BingSpeciesProvider
from fishagent.providers.species_extract import SpeciesExtractor
from fishagent.providers.species_mock import MockSpeciesProvider
from fishagent.providers.species_none import NullSpeciesProvider
from fishagent.providers.weather_mock import MockWeatherProvider

logger = logging.getLogger(__name__)


def _build_species_extractor() -> SpeciesExtractor | None:
    """Build the Phase 2 LLM extractor, or None when no key is configured.

    Reuses the same OpenAI-compatible settings as the agent, so one LLM_API_KEY
    covers both features and Mock mode never calls out.
    """
    llm = load_llm_settings()
    if not llm.api_key or llm.mock_mode:
        logger.info("species page fetch enabled without LLM key; extraction disabled")
        return None
    try:
        from openai import AsyncOpenAI
    except ImportError:  # pragma: no cover - openai is a hard dependency
        logger.warning("openai package unavailable; species extraction disabled")
        return None
    client = AsyncOpenAI(
        api_key=llm.api_key,
        base_url=llm.base_url,
        timeout=llm.timeout_seconds,
    )
    return SpeciesExtractor(client, llm.model)


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


def get_species_provider() -> SpeciesProvider:
    settings = get_settings()
    choice = (settings.species_provider or "").strip().lower()
    if not choice:
        return MockSpeciesProvider() if settings.mock_mode else NullSpeciesProvider()
    if choice == "mock":
        return MockSpeciesProvider()
    if choice == "bing":
        return BingSpeciesProvider(
            timeout_seconds=settings.species_timeout_seconds,
            extractor=_build_species_extractor() if settings.species_page_fetch_enabled else None,
            enable_page_fetch=settings.species_page_fetch_enabled,
        )
    if choice in ("none", "disabled"):
        return NullSpeciesProvider()
    logger.warning("unknown FISHAGENT_SPECIES_PROVIDER=%s; using none", choice)
    return NullSpeciesProvider()
