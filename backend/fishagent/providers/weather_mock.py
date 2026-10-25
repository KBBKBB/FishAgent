"""Deterministic weather mock with five scenario profiles and PRD date seeds."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from fishagent.core.rules import ensure_shanghai
from fishagent.schemas import WeatherSnapshot

_PROFILES: dict[str, dict[str, Any]] = {
    # PRD 5.1: 2026-04-12 05:30 local, pressure falling 5 hPa, sunrise window.
    "excellent": {
        "pressure_msl": 1012.0,
        "pressure_change_24h": -5.0,
        "pressure_change_3h": -1.2,
        "pressure_change_6h": -2.0,
        "temperature": 20.0,
        "temperature_change_24h": 1.0,
        "diurnal_range": 9.0,
        "wind_speed_ms": 4.2,
        "wind_direction": "东南风",
        "wind_level": 3,
        "precipitation_mm": 0.0,
        "cloud_cover_pct": 55.0,
        "sunrise": "06:12",
        "sunset": "17:48",
        "is_thunderstorm": False,
        "consecutive_hot_dry_days": 0,
        "last_rain_hours_ago": None,
    },
    # 2026-04-13 08:00 local, stable pressure, light cloud, 4-level wind.
    "good": {
        "pressure_msl": 1010.0,
        "pressure_change_24h": -1.0,
        "pressure_change_3h": 0.3,
        "pressure_change_6h": -0.2,
        "temperature": 22.0,
        "temperature_change_24h": 4.0,
        "diurnal_range": 9.0,
        "wind_speed_ms": 6.2,
        "wind_direction": "南风",
        "wind_level": 4,
        "precipitation_mm": 0.0,
        "cloud_cover_pct": 60.0,
        "sunrise": "06:40",
        "sunset": "17:50",
        "is_thunderstorm": False,
        "consecutive_hot_dry_days": 0,
        "last_rain_hours_ago": None,
    },
    # 2026-04-14 10:00 local, pressure rising 4 hPa, continuous hot-dry spell.
    "fair": {
        "pressure_msl": 1008.0,
        "pressure_change_24h": 4.0,
        "pressure_change_3h": 1.0,
        "pressure_change_6h": 2.0,
        "temperature": 26.0,
        "temperature_change_24h": 6.0,
        "diurnal_range": 10.0,
        "wind_speed_ms": 6.5,
        "wind_direction": "西南风",
        "wind_level": 4,
        "precipitation_mm": 0.0,
        "cloud_cover_pct": 20.0,
        "sunrise": "06:10",
        "sunset": "17:52",
        "is_thunderstorm": False,
        "consecutive_hot_dry_days": 4,
        "last_rain_hours_ago": None,
    },
    # 2026-04-15 12:00 local, pressure surging 10 hPa, hot and clear.
    "poor": {
        "pressure_msl": 1018.0,
        "pressure_change_24h": 10.0,
        "pressure_change_3h": 3.0,
        "pressure_change_6h": 5.0,
        "temperature": 30.0,
        "temperature_change_24h": 9.0,
        "diurnal_range": 11.0,
        "wind_speed_ms": 6.5,
        "wind_direction": "西风",
        "wind_level": 4,
        "precipitation_mm": 0.0,
        "cloud_cover_pct": 20.0,
        "sunrise": "06:08",
        "sunset": "17:55",
        "is_thunderstorm": False,
        "consecutive_hot_dry_days": 5,
        "last_rain_hours_ago": None,
    },
    # 2026-06-20 14:00 local, thunderstorm, 6-level wind, pressure plunge.
    "no_go": {
        "pressure_msl": 999.0,
        "pressure_change_24h": -12.0,
        "pressure_change_3h": -4.0,
        "pressure_change_6h": -7.0,
        "temperature": 33.0,
        "temperature_change_24h": -9.0,
        "diurnal_range": 10.0,
        "wind_speed_ms": 12.0,
        "wind_direction": "北风",
        "wind_level": 6,
        "precipitation_mm": 45.0,
        "cloud_cover_pct": 95.0,
        "sunrise": "05:00",
        "sunset": "19:00",
        "is_thunderstorm": True,
        "consecutive_hot_dry_days": 0,
        "last_rain_hours_ago": None,
    },
}

_SEED_DATES: dict[date, str] = {
    date(2026, 4, 12): "excellent",
    date(2026, 4, 13): "good",
    date(2026, 4, 14): "fair",
    date(2026, 4, 15): "poor",
    date(2026, 6, 20): "no_go",
}

_SCENARIOS = ("excellent", "good", "fair", "poor", "no_go")


def _seeded_scenario(lat: float, lon: float, local_at: datetime) -> str:
    seed = f"{lat:.3f}|{lon:.3f}|{local_at.date().isoformat()}"
    bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 25:
        return "excellent"
    if bucket < 60:
        return "good"
    if bucket < 85:
        return "fair"
    return "poor"


class MockWeatherProvider:
    """Deterministic Mock weather. `scenario` wins over date seeds."""

    async def get_weather(
        self,
        lat: float,
        lon: float,
        at: datetime,
        scenario: str | None = None,
    ) -> WeatherSnapshot:
        local_at = ensure_shanghai(at)
        if scenario in _SCENARIOS:
            chosen = scenario
        elif local_at.date() in _SEED_DATES:
            chosen = _SEED_DATES[local_at.date()]
        else:
            chosen = _seeded_scenario(lat, lon, local_at)
        return WeatherSnapshot(source_label="Open-Meteo（Mock）", **_PROFILES[chosen])
