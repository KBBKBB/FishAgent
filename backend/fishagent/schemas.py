"""Pydantic models shared by providers, the rule engine and the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Impact = Literal["positive", "neutral", "negative"]
AlertLevel = Literal["danger", "warning", "info"]
EntryPrecision = Literal["entr_location", "center_fallback"]


class LatLon(BaseModel):
    lat: float
    lon: float


class FactorOut(BaseModel):
    code: str
    name: str
    score: int
    max_score: int
    impact: Impact
    detail: str


class BestWindow(BaseModel):
    start: str
    end: str
    label: str


class AlertOut(BaseModel):
    code: str
    level: AlertLevel
    message: str
    forced: bool = True


class WeatherSnapshot(BaseModel):
    """Normalised weather input for the pure rule engine.

    Units: hPa, Celsius, m/s, mm/day, percent. Mock and real providers both
    produce this shape, and tests may build it directly.
    """

    pressure_msl: float = 1013.0
    pressure_change_24h: float = 0.0
    pressure_change_3h: float = 0.0
    pressure_change_6h: float = 0.0
    temperature: float = 20.0
    temperature_change_24h: float = 0.0
    diurnal_range: float = 8.0
    wind_speed_ms: float = 3.5
    wind_direction: str = "东南风"
    wind_level: int | None = None
    precipitation_mm: float = 0.0
    cloud_cover_pct: float = 50.0
    sunrise: str = "06:00"
    sunset: str = "18:00"
    is_thunderstorm: bool = False
    pressure_percentile: float | None = None
    consecutive_hot_dry_days: int = 0
    last_rain_hours_ago: float | None = None
    source_label: str = "Open-Meteo（Mock）"


class WeatherSummary(BaseModel):
    pressure_msl: float
    pressure_change_24h: float
    pressure_change_3h: float
    pressure_change_6h: float
    temperature: float
    temperature_change_24h: float
    diurnal_range: float
    wind_speed_ms: float
    wind_level: int
    wind_direction: str
    precipitation_mm: float
    cloud_cover_pct: float
    sunrise: str
    sunset: str
    is_thunderstorm: bool


class FishActivityResult(BaseModel):
    score: int
    band: str
    advice: str
    recommendation: str
    factors: list[FactorOut]
    top_factors: list[FactorOut]
    best_windows: list[BestWindow]
    water_depth: str
    suitable_species: list[str]
    alerts: list[AlertOut]


class FishActivityResponse(BaseModel):
    score: int
    band: str
    advice: str
    recommendation: str
    factors: list[FactorOut]
    top_factors: list[FactorOut]
    best_windows: list[BestWindow]
    water_depth: str
    suitable_species: list[str]
    alerts: list[AlertOut]
    weather_summary: WeatherSummary
    data_sources: list[str]
    ai_disclosure: str
    timezone: str
    generated_at: str


class SpotCandidate(BaseModel):
    id: str
    name: str
    water_type: str
    address: str = ""
    location_gcj02: LatLon
    entry_location_gcj02: LatLon | None = None
    downwind: bool = False


class SpotOut(BaseModel):
    id: str
    name: str
    water_type: str
    address: str
    location_gcj02: LatLon
    entry_location_gcj02: LatLon
    entry_precision: EntryPrecision
    distance_m: int
    drive_seconds_out: int
    drive_seconds_back: int
    drive_seconds_round_trip: int
    drive_minutes_one_way: int
    fish_score: int
    total_score: float
    reasons: list[str]
    navigation_url: str


class UserLocationOut(BaseModel):
    wgs84: LatLon
    gcj02: LatLon


class FilteredStats(BaseModel):
    total_candidates: int = Field(ge=0)
    forbidden: int = Field(ge=0)
    unavailable: int = Field(default=0, ge=0)
    over_two_hours: int = Field(ge=0)
    eligible: int = Field(ge=0)
    returned: int = Field(ge=0)
    truncated_by_limit: int = Field(ge=0)
    evaluated: int = Field(default=0, ge=0)
    unevaluated: int = Field(default=0, ge=0)


class SpotsMeta(BaseModel):
    mock_mode: bool
    radius_km: float
    round_trip_limit_seconds: int
    traffic_basis: str
    generated_at: str


class SpotRecommendationResponse(BaseModel):
    user_location: UserLocationOut
    spots: list[SpotOut]
    filtered: FilteredStats
    meta: SpotsMeta


class HealthResponse(BaseModel):
    status: str
    version: str
    mock_mode: bool


class DemoConfigResponse(BaseModel):
    mock_mode: bool
    default_location: dict[str, float | str]
    scenarios: list[str]
    ai_disclosure: str
    disclaimer: str
    timezone: str
