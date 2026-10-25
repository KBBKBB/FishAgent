"""Open-Meteo adapter (no key required for the non-commercial tier)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from fishagent.core.rules import ensure_shanghai, wind_level_from_speed
from fishagent.providers.base import ProviderError
from fishagent.schemas import WeatherSnapshot

_DIRECTIONS = ("北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风")


def _direction_label(degrees: float) -> str:
    index = int((degrees + 22.5) // 45) % 8
    return _DIRECTIONS[index]


def _number(series: list[Any] | None, index: int, default: float = 0.0) -> float:
    if not series:
        return default
    if index < 0:
        index = 0
    if index >= len(series):
        index = len(series) - 1
    value = series[index]
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nearest_index(times: list[str] | None, target: datetime) -> int:
    if not times:
        return 0
    best_index = 0
    best_delta: float | None = None
    for index, raw in enumerate(times):
        try:
            parsed = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=target.tzinfo)
        delta = abs((parsed - target).total_seconds())
        if best_delta is None or delta < best_delta:
            best_index, best_delta = index, delta
    return best_index


def _average(series: list[Any] | None, start: int, length: int) -> float:
    if not series:
        return 0.0
    window = series[start : start + length]
    numbers = []
    for value in window:
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(numbers) / len(numbers) if numbers else 0.0


class OpenMeteoWeatherProvider:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def get_weather(
        self,
        lat: float,
        lon: float,
        at: datetime,
        scenario: str | None = None,
    ) -> WeatherSnapshot:
        # `scenario` is a Mock-only switch; real providers ignore it.
        local_at = ensure_shanghai(at)
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "timezone": "Asia/Shanghai",
            "past_days": 1,
            "forecast_days": 2,
            "current": "temperature_2m,pressure_msl,cloud_cover,wind_speed_10m,"
            "wind_direction_10m,precipitation,weather_code",
            "hourly": "pressure_msl,temperature_2m,precipitation,cloud_cover,"
            "wind_speed_10m,wind_direction_10m",
            "daily": "sunrise,sunset,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/forecast", params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("气象数据获取失败，请稍后重试") from exc
        try:
            return self._parse(payload, local_at)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("气象数据解析失败") from exc

    def _parse(self, payload: dict[str, Any], local_at: datetime) -> WeatherSnapshot:
        hourly = payload["hourly"]
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}

        times = hourly.get("time") or []
        index = _nearest_index(times, local_at)
        pressure = _number(hourly.get("pressure_msl"), index, 1013.0)
        pressure_3h = _number(hourly.get("pressure_msl"), index + 3, pressure)
        pressure_6h = _number(hourly.get("pressure_msl"), index + 6, pressure)
        pressure_24h = _number(hourly.get("pressure_msl"), index + 24, pressure)
        temperature = _average(hourly.get("temperature_2m"), index, 24) or _number(
            current.get("temperature_2m"), 0, 20.0
        )
        temperature_24h = _number(hourly.get("temperature_2m"), index + 24, temperature)

        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        diurnal_range = 8.0
        if highs and lows:
            try:
                diurnal_range = max(0.0, float(highs[0]) - float(lows[0]))
            except (TypeError, ValueError):
                diurnal_range = 8.0

        wind_kmh = _number(hourly.get("wind_speed_10m"), index, 12.0)
        wind_ms = wind_kmh / 3.6
        wind_direction = _direction_label(
            _number(hourly.get("wind_direction_10m"), index, 180.0)
        )

        sunrise = _time_part((daily.get("sunrise") or ["06:00"])[0], "06:00")
        sunset = _time_part((daily.get("sunset") or ["18:00"])[0], "18:00")
        precipitation = _number(daily.get("precipitation_sum"), 0, 0.0)
        if not precipitation:
            precipitation = _number(hourly.get("precipitation"), index, 0.0)
        weather_code = int(_number([current.get("weather_code")], 0, 0))
        cloud = _number(hourly.get("cloud_cover"), index, 50.0)

        return WeatherSnapshot(
            pressure_msl=pressure,
            pressure_change_24h=pressure_24h - pressure,
            pressure_change_3h=pressure_3h - pressure,
            pressure_change_6h=pressure_6h - pressure,
            temperature=temperature,
            temperature_change_24h=temperature_24h - temperature,
            diurnal_range=diurnal_range,
            wind_speed_ms=wind_ms,
            wind_direction=wind_direction,
            wind_level=wind_level_from_speed(wind_ms),
            precipitation_mm=precipitation,
            cloud_cover_pct=cloud,
            sunrise=sunrise,
            sunset=sunset,
            is_thunderstorm=weather_code in (95, 96, 99),
            source_label="Open-Meteo",
        )


def _time_part(value: Any, fallback: str) -> str:
    try:
        text = str(value)
        return text.split("T", 1)[1][:5] if "T" in text else text[:5]
    except (AttributeError, IndexError):
        return fallback
