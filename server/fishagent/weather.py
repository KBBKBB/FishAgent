"""Open-Meteo 气象数据接入 —— 对应 M1-T08。

关键取值约定 (TechStack §4.1):
  · 统一使用 pressure_msl (海平面气压), 不用 surface_pressure;
  · 天气查询使用 WGS84 原始坐标 (Open-Meteo 不接受 GCJ-02);
  · F1 需 24h 变化量 + 3h/6h 短时变化率; 优先使用未来 24h 预报变化量;
  · F2 需当地近 30 天 pressure_msl 分布用于归一化。

Open-Meteo 免费层为 Non-Commercial (CC BY 4.0); 商用需购买 Key (见数据源授权清单)。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .config import OPEN_METEO_ARCHIVE, OPEN_METEO_BASE
from .http import get_json

HOURLY_VARS = (
    "pressure_msl,temperature_2m,relative_humidity_2m,"
    "precipitation,wind_speed_10m,wind_direction_10m,cloud_cover"
)


@dataclass
class WeatherSeries:
    latitude: float
    longitude: float
    timezone: str
    times: list[str] = field(default_factory=list)
    variables: dict[str, list[float | None]] = field(default_factory=dict)
    daily: dict[str, list[Any]] = field(default_factory=dict)

    def index_of(self, iso_prefix: str) -> int | None:
        """找到时间前缀 (如 '2026-10-10T14') 对应的小时下标。"""
        for i, t in enumerate(self.times):
            if t.startswith(iso_prefix):
                return i
        return None

    def value_at(self, var: str, idx: int) -> float | None:
        seq = self.variables.get(var) or []
        if 0 <= idx < len(seq):
            return seq[idx]
        return None

    def delta(self, var: str, idx_now: int, hours: int) -> float | None:
        """idx_now 相对 hours 小时前的变化量 (未来用负的 hours)。"""
        a = self.value_at(var, idx_now)
        b = self.value_at(var, idx_now + hours)
        if a is None or b is None:
            return None
        return a - b


def _get_series(url: str, params: dict[str, Any], timeout: float = 8.0) -> WeatherSeries:
    data = get_json(url, params, timeout=timeout)
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    variables = {k: v for k, v in hourly.items() if k != "time"}
    return WeatherSeries(
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        timezone=data.get("timezone", "UTC"),
        times=times,
        variables=variables,
        daily=data.get("daily", {}),
    )


def fetch_forecast(
    lat: float,
    lng: float,
    *,
    past_days: int = 2,
    forecast_days: int = 2,
    timeout: float = 8.0,
) -> WeatherSeries:
    """取实时+预报序列 (含过去 2 天, 便于计算 24h 变化)。坐标用 WGS84。"""
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": HOURLY_VARS,
        "daily": "sunrise,sunset,temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }
    return _get_series(f"{OPEN_METEO_BASE}/v1/forecast", params, timeout)


def fetch_archive_pressure(
    lat: float,
    lng: float,
    *,
    days: int = 30,
    timeout: float = 15.0,
) -> list[float]:
    """近 N 天 pressure_msl 历史序列, 用于 F2 当地气候态归一化。

    优先用 Archive API; 失败时回退到 forecast 的 past_days。
    """
    end = dt.date.today() - dt.timedelta(days=2)  # 归档数据有 ~2 天延迟
    start = end - dt.timedelta(days=days)
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": "pressure_msl",
        "timezone": "auto",
    }
    series = _get_series(f"{OPEN_METEO_ARCHIVE}/v1/archive", params, timeout)
    return [v for v in series.variables.get("pressure_msl", []) if v is not None]


def percentile(values: list[float], value: float) -> float:
    """value 在 values 分布中的百分位 (0~100)。"""
    if not values:
        return 50.0
    below = sum(1 for v in values if v <= value)
    return 100.0 * below / len(values)
