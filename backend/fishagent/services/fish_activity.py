"""Fish-activity service: weather provider -> pure rule engine -> API response."""

from __future__ import annotations

from datetime import datetime, timezone

from fishagent.core.rules import (
    ALLOWED_SPECIES,
    compute_fish_activity,
    wind_level_from_speed,
)
from fishagent.errors import ApiError
from fishagent.providers.base import ProviderError, WeatherProvider
from fishagent.schemas import FishActivityResponse, WeatherSnapshot, WeatherSummary

BUSINESS_TIMEZONE = "Asia/Shanghai"
AI_DISCLOSURE = "本结论由 AI 辅助生成，仅供参考，不承诺渔获。"
RULE_ENGINE_SOURCE = "FishAgent 规则引擎 v1"


def validate_species(species: str | None) -> str | None:
    if species is None:
        return None
    value = species.strip()
    if not value:
        return None
    if value not in ALLOWED_SPECIES:
        raise ApiError(
            status_code=422,
            code="INVALID_SPECIES",
            message=f"不支持的鱼种：{species}，可选：{'、'.join(ALLOWED_SPECIES)}",
            fields=[{"field": "species", "message": "仅支持 " + "、".join(ALLOWED_SPECIES)}],
        )
    return value


def parse_at(value: str | None) -> datetime:
    if value is None or not value.strip():
        return datetime.now(timezone.utc)
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="at 参数必须是 ISO 8601 时间",
            fields=[
                {
                    "field": "at",
                    "message": "示例：2026-10-21T10:00:00Z 或 2026-10-21T18:00:00",
                }
            ],
        ) from exc
    return parsed


def utc_timestamp(moment: datetime | None = None) -> str:
    value = moment or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_weather(weather: WeatherSnapshot) -> WeatherSummary:
    return WeatherSummary(
        pressure_msl=weather.pressure_msl,
        pressure_change_24h=weather.pressure_change_24h,
        pressure_change_3h=weather.pressure_change_3h,
        pressure_change_6h=weather.pressure_change_6h,
        temperature=weather.temperature,
        temperature_change_24h=weather.temperature_change_24h,
        diurnal_range=weather.diurnal_range,
        wind_speed_ms=weather.wind_speed_ms,
        wind_level=(
            weather.wind_level
            if weather.wind_level is not None
            else wind_level_from_speed(weather.wind_speed_ms)
        ),
        wind_direction=weather.wind_direction,
        precipitation_mm=weather.precipitation_mm,
        cloud_cover_pct=weather.cloud_cover_pct,
        sunrise=weather.sunrise,
        sunset=weather.sunset,
        is_thunderstorm=weather.is_thunderstorm,
    )


async def build_fish_activity(
    provider: WeatherProvider,
    *,
    lat: float,
    lon: float,
    at: str | None,
    scenario: str | None,
    species: str | None,
) -> FishActivityResponse:
    normalized_species = validate_species(species)
    moment = parse_at(at)
    try:
        weather = await provider.get_weather(lat, lon, moment, scenario)
    except ProviderError as exc:
        raise ApiError(
            status_code=502,
            code="WEATHER_PROVIDER_ERROR",
            message="天气数据暂时不可用，请稍后再试",
        ) from exc

    result = compute_fish_activity(weather, moment, normalized_species)
    return FishActivityResponse(
        **result.model_dump(),
        weather_summary=summarize_weather(weather),
        data_sources=[weather.source_label, RULE_ENGINE_SOURCE],
        ai_disclosure=AI_DISCLOSURE,
        timezone=BUSINESS_TIMEZONE,
        generated_at=utc_timestamp(),
    )
