"""Pydantic models shared by providers, the rule engine and the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Impact = Literal["positive", "neutral", "negative"]
AlertLevel = Literal["danger", "warning", "info"]
EntryPrecision = Literal["entr_location", "center_fallback"]
# ``typical`` is not a cited source: it means the list was derived from the
# water *type* because nothing described this specific water body. Callers need
# to distinguish it from ``bing``/``xiaohongshu`` to word the note honestly.
SpeciesSource = Literal["xiaohongshu", "bing", "typical", "none"]


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


class PlaceCandidate(BaseModel):
    """A location the user can pick as their starting point.

    Coordinates are WGS84: AMap answers in GCJ-02 and the provider converts at
    its own boundary, so everything above that is one datum.
    """

    name: str
    address: str = ""
    lat: float
    lon: float
    # "place" for text search; the water type ("湖泊"/"河流"…) for nearby water.
    kind: str = "place"
    distance_m: int | None = None


class PlaceSearchResponse(BaseModel):
    """Location-picker results.

    ``resolved`` separates "searched, nothing found" from "this provider cannot
    search at all", so the UI can offer the manual form as the right next step
    instead of telling the user their place does not exist.
    """

    results: list[PlaceCandidate]
    query: str = ""
    resolved: bool = True


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
    # Recalled candidates closer than the ring's inner edge. Without this the
    # invariants below would not add up for a 10~50 km search, and a reader
    # could not tell "excluded for being too near" from "never found".
    within_min_radius: int = Field(default=0, ge=0)
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
    # The ring the search covered; equal when min is 0, which is the plain
    # "everything within radius_km" case.
    min_radius_km: float = 0.0
    radius_km: float
    round_trip_limit_seconds: int
    traffic_basis: str
    generated_at: str
    # How the returned set was spread out. Reported so a clustered-looking
    # result can be told apart from a strategy that did not run: min_separation_m
    # is the distance finally enforced, and separation_relaxed says the
    # requested spread could not be met and had to be widened.
    selection_strategy: str = "score"
    min_separation_m: int = 0
    separation_relaxed: bool = False


class SpotRecommendationResponse(BaseModel):
    user_location: UserLocationOut
    spots: list[SpotOut]
    filtered: FilteredStats
    meta: SpotsMeta


class SpotSpeciesQuery(BaseModel):
    """One water body to look up in community posts."""

    spot_id: str | None = Field(default=None, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    water_type: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name 不能为空")
        return text


class SpeciesQueryRequest(BaseModel):
    spots: list[SpotSpeciesQuery] = Field(..., min_length=1, max_length=10)


class SpotSpeciesResult(BaseModel):
    spot_id: str | None = None
    spot_name: str
    species: list[str]
    has_recommendation: bool
    source: SpeciesSource
    source_label: str = ""
    note: str


class SpeciesRecommendationResponse(BaseModel):
    results: list[SpotSpeciesResult]
    provider: str
    degraded: bool = False
    source_disclosure: str
    generated_at: str


class HealthResponse(BaseModel):
    status: str
    version: str
    # Content hash of the served H5 shell; lets an open page notice a deploy.
    # Empty only if the web directory is missing.
    build: str = ""
    mock_mode: bool


class DemoConfigResponse(BaseModel):
    mock_mode: bool
    default_location: dict[str, float | str]
    scenarios: list[str]
    ai_disclosure: str
    disclaimer: str
    timezone: str
