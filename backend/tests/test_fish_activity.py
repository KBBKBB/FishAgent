from __future__ import annotations

import re

import pytest
from conftest import (
    FACTOR_MAX,
    PRD_AT_SEEDS,
    PROMISE_PATTERNS,
    SCENARIOS,
    VALID_SPECIES,
    assert_iso_utc,
    assert_unified_error,
    fish_params,
)

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
REQUIRED_WEATHER_FIELDS = (
    "pressure_msl",
    "pressure_change_24h",
    "pressure_change_3h",
    "pressure_change_6h",
    "temperature",
    "temperature_change_24h",
    "diurnal_range",
    "wind_speed_ms",
    "wind_level",
    "wind_direction",
    "precipitation_mm",
    "cloud_cover_pct",
    "sunrise",
    "sunset",
    "is_thunderstorm",
)


def get_fish(client, **overrides):
    response = client.get("/api/fish-activity", params=fish_params(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


WINDOW_COUNTS = {"excellent": 2, "good": 2, "fair": 2, "poor": 1, "no_go": 0}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenario_maps_to_band(client, scenario):
    expected = SCENARIOS[scenario]
    payload = get_fish(client, scenario=scenario)

    assert payload["band"] == expected["band"]
    assert expected["min"] <= payload["score"] <= expected["max"]
    assert payload["advice"] == expected["advice"]
    assert len(payload["best_windows"]) == WINDOW_COUNTS[scenario]

    if scenario == "no_go":
        assert "值得去" not in payload["recommendation"]
        assert "强烈建议" not in payload["recommendation"]
    elif scenario == "excellent":
        assert payload["alerts"] == []


@pytest.mark.parametrize("seed,band", list(PRD_AT_SEEDS.items()))
def test_prd_at_seeds_compatibility(client, seed, band):
    payload = get_fish(client, at=seed)
    assert payload["band"] == band, f"PRD seed {seed} should map to {band}, got {payload['band']}"


def test_factor_invariants_and_top3(client):
    payload = get_fish(client, scenario="fair")
    factors = payload["factors"]

    assert [item["code"] for item in factors] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    assert sum(item["score"] for item in factors) == payload["score"]
    assert 0 <= payload["score"] <= 100

    for factor in factors:
        assert factor["max_score"] == FACTOR_MAX[factor["code"]]
        assert isinstance(factor["score"], int)
        assert 0 <= factor["score"] <= factor["max_score"]
        ratio = factor["score"] / factor["max_score"]
        if ratio >= 0.8:
            assert factor["impact"] == "positive"
        elif ratio <= 0.5:
            assert factor["impact"] == "negative"
        else:
            assert factor["impact"] == "neutral"

    top = payload["top_factors"]
    assert len(top) == 3
    expected = sorted(
        factors,
        key=lambda item: (-item["score"] / item["max_score"], -item["score"], item["code"]),
    )[:3]
    assert [item["code"] for item in top] == [item["code"] for item in expected]

    by_code = {item["code"]: item for item in factors}
    for item in top:
        assert item == by_code[item["code"]]


def test_no_go_alerts_schema_and_forced_content(client):
    payload = get_fish(client, scenario="no_go")
    alerts = payload["alerts"]
    assert alerts, "no_go must contain forced alerts"

    for alert in alerts:
        assert set(alert) >= {"code", "level", "message", "forced"}
        assert alert["level"] in {"danger", "warning", "info"}
        assert isinstance(alert["message"], str) and alert["message"]
        assert isinstance(alert["forced"], bool)

    forced_danger = [
        alert
        for alert in alerts
        if alert["level"] == "danger" and alert["code"] in {"RAINSTORM", "GALE"}
    ]
    assert forced_danger, f"no_go must include RAINSTORM or GALE danger alert: {alerts}"
    assert all(alert["forced"] is True for alert in forced_danger)

    if payload["weather_summary"]["pressure_change_24h"] < -8:
        plunge = [alert for alert in alerts if alert["code"] == "PRESSURE_PLUNGE"]
        assert plunge, "24h pressure plunge must emit PRESSURE_PLUNGE"
        assert plunge[0]["level"] == "warning"
        assert "2" in plunge[0]["message"] and "4" in plunge[0]["message"]


def test_weather_summary_is_complete(client):
    payload = get_fish(client, scenario="fair")
    weather = payload["weather_summary"]
    for field in REQUIRED_WEATHER_FIELDS:
        assert field in weather, f"missing weather field: {field}"
    for field in ("sunrise", "sunset"):
        assert TIME_RE.match(weather[field]), f"invalid {field}: {weather[field]}"


def test_best_windows_format(client):
    for scenario in ("excellent", "good", "fair", "poor"):
        payload = get_fish(client, scenario=scenario)
        for window in payload["best_windows"]:
            assert TIME_RE.match(window["start"]), window
            assert TIME_RE.match(window["end"]), window
            assert window["start"] < window["end"], window
            assert window["label"]


def test_valid_species(client):
    for species in VALID_SPECIES:
        payload = get_fish(client, scenario="good", species=species)
        assert payload["suitable_species"]
        assert all(isinstance(item, str) for item in payload["suitable_species"])


def test_invalid_species_rejected(client):
    response = client.get("/api/fish-activity", params=fish_params(species="鲨鱼"))
    assert_unified_error(response, 422, "INVALID_SPECIES")


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 91, "lon": 120.1551},
        {"lat": -91, "lon": 120.1551},
        {"lat": 30.2741, "lon": 181},
        {"lat": 30.2741, "lon": -181},
        {"lon": 120.1551},
        {"lat": 30.2741},
    ],
)
def test_invalid_coordinates_rejected(client, params):
    response = client.get("/api/fish-activity", params=params)
    assert_unified_error(response, 422, "VALIDATION_ERROR")


def test_invalid_scenario_rejected(client):
    response = client.get("/api/fish-activity", params=fish_params(scenario="bogus"))
    assert_unified_error(response, 422, "VALIDATION_ERROR")


def test_naive_at_is_interpreted_as_shanghai_time(client):
    aware = get_fish(client, scenario="fair", at="2026-10-21T10:00:00Z")
    naive = get_fish(client, scenario="fair", at="2026-10-21T18:00:00")
    assert naive["score"] == aware["score"]
    assert naive["band"] == aware["band"]
    assert naive["factors"] == aware["factors"]
    assert naive["best_windows"] == aware["best_windows"]


def test_response_timezone_and_generated_at(client):
    payload = get_fish(client, scenario="good")
    assert payload["timezone"] == "Asia/Shanghai"
    assert_iso_utc(payload["generated_at"])


def test_data_sources_and_ai_disclosure(client):
    payload = get_fish(client, scenario="good")
    assert any("Mock" in item for item in payload["data_sources"])
    disclosure = payload["ai_disclosure"]
    assert "AI" in disclosure
    assert "仅供参考" in disclosure
    assert "不承诺渔获" in disclosure


def test_no_catch_promises_in_text(client):
    for scenario in SCENARIOS:
        payload = get_fish(client, scenario=scenario)
        text = payload["advice"] + payload["recommendation"]
        for phrase in PROMISE_PATTERNS:
            assert phrase not in text, f"promise phrase {phrase} in {scenario}: {text}"


def test_deterministic_for_same_input(client):
    first = get_fish(client, scenario="fair")
    second = get_fish(client, scenario="fair")
    third = get_fish(client, scenario="fair")
    for payload in (second, third):
        assert payload["score"] == first["score"]
        assert payload["band"] == first["band"]
        assert payload["factors"] == first["factors"]
        assert payload["top_factors"] == first["top_factors"]
        assert payload["best_windows"] == first["best_windows"]


# --- Water-depth strategy ---------------------------------------------------
#
# The card used to read the temperature alone: three branches, so every request
# between 5 and 32 degC got the identical sentence. It now starts from a
# temperature-implied layer and lets the factors the engine already scores move
# it. These tests pin the properties that make it worth showing.


def _depth(weather, *, month=4, day=12, hour=8, minute=0):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import _water_depth

    now = datetime(2026, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    return _water_depth(weather, now)


def _weather(**overrides):
    from fishagent.schemas import WeatherSnapshot

    return WeatherSnapshot(**overrides)


def test_water_depth_varies_with_weather_not_only_temperature():
    """The whole point of the change: same temperature, different advice."""
    cool_overcast = _depth(_weather(temperature=16.0, cloud_cover_pct=85, wind_level=3))
    cool_clear_calm = _depth(
        _weather(temperature=16.0, cloud_cover_pct=10, wind_level=0, wind_speed_ms=0.4)
    )
    assert cool_overcast != cool_clear_calm


def test_water_depth_always_offers_a_fallback():
    """It is a guess about water we cannot measure; it must not read as fact."""
    for weather in (
        _weather(temperature=3.0),
        _weather(temperature=16.0),
        _weather(temperature=30.0, cloud_cover_pct=20),
        _weather(temperature=35.0),
    ):
        text = _depth(weather)
        assert "先钓" in text and "无口再试" in text, text


def test_cold_water_points_deeper_than_warm_water():
    cold = _depth(_weather(temperature=4.0, cloud_cover_pct=20))
    warm = _depth(_weather(temperature=24.0, cloud_cover_pct=55))
    # Compare the starting layer's lower bound as a coarse ordering check.
    def lower_bound(text):
        return float(text.split("先钓 ")[1].split("m")[0].split("–")[0])

    assert lower_bound(cold) > lower_bound(warm)


def test_rain_shifts_advice_shallower_and_says_why():
    dry = _depth(_weather(temperature=16.0, cloud_cover_pct=60))
    after_rain = _depth(_weather(temperature=16.0, cloud_cover_pct=60, last_rain_hours_ago=2.0))
    assert dry != after_rain
    # The card names the cause, so the movement is not unexplained.
    assert "雨后" in after_rain


def test_pressure_plunge_shifts_shallower():
    steady = _depth(_weather(temperature=16.0, cloud_cover_pct=60))
    falling = _depth(_weather(temperature=16.0, cloud_cover_pct=60, pressure_change_24h=-5.0))
    assert steady != falling
    assert "气压" in falling


def test_wind_means_opposite_things_in_cold_and_warm_water():
    """Reusing summer reasoning for winter would give plainly wrong advice."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import _depth_modifiers

    now = datetime(2026, 1, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def shift(weather, at):
        return sum(delta for delta, _ in _depth_modifiers(weather, at))

    cold_shift = shift(_weather(temperature=8.0, wind_level=3, wind_speed_ms=4.0), now)
    warm_shift = shift(
        _weather(temperature=22.0, wind_level=3, wind_speed_ms=4.0),
        now.replace(month=7, day=15),
    )
    # Cold + wind -> deeper; warm + the same wind -> shallower.
    assert cold_shift > warm_shift


def test_depth_advice_is_deterministic():
    weather = _weather(temperature=18.0, cloud_cover_pct=40, pressure_change_24h=-3.0)
    assert _depth(weather) == _depth(weather)


def test_no_go_band_withholds_depth_advice():
    """Telling someone where to fish on a 'do not go' day is self-contradictory."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import _water_depth

    now = datetime(2026, 4, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    storm = _weather(
        temperature=26.0,
        is_thunderstorm=True,
        precipitation_mm=45.0,
        wind_level=6,
        cloud_cover_pct=95,
    )
    assert "先钓" not in _water_depth(storm, now, band="劝退")
    # The non-suppressed path still gives strategy for every other band.
    assert "先钓" in _water_depth(_weather(temperature=16.0), now, band="良好")


# --- Species must agree with the depth advice -------------------------------
#
# Both used to read the temperature alone, so they drifted apart the moment the
# depth line started using the other factors: the card could say "钓 4-5m 深水"
# while still recommending warm-water 草鱼/鲢鳙. They now read one plan.


def test_requested_species_is_always_first():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import compute_fish_activity

    now = datetime(2026, 4, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for species in ("鲫鱼", "鲤鱼", "草鱼", "鲢鳙"):
        for weather in (
            _weather(temperature=4.0),
            _weather(temperature=16.0),
            _weather(temperature=30.0),
        ):
            result = compute_fish_activity(weather, now, species)
            assert result.suitable_species[0] == species, (
                f"{species} asked for but not first at {weather.temperature}C"
            )


def test_requested_species_survives_a_go_against_day():
    """The contract says a valid species is reflected; it is not dropped."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import compute_fish_activity

    now = datetime(2026, 4, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    storm = _weather(
        temperature=26.0, is_thunderstorm=True, precipitation_mm=45.0, wind_level=6
    )
    result = compute_fish_activity(storm, now, "鲤鱼")
    assert result.band == "劝退"
    assert result.suitable_species == ["鲤鱼"]


def test_species_never_empty_in_any_band():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import compute_fish_activity

    now = datetime(2026, 4, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for weather in (
        _weather(temperature=4.0),
        _weather(temperature=26.0),
        _weather(temperature=26.0, is_thunderstorm=True, precipitation_mm=45.0),
    ):
        result = compute_fish_activity(weather, now)
        assert result.suitable_species, f"empty species at {weather.temperature}C"


def test_only_allowed_species_are_recommended():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import ALLOWED_SPECIES, compute_fish_activity

    now = datetime(2026, 4, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for temperature in (0.0, 10.0, 20.0, 26.0, 35.0):
        result = compute_fish_activity(_weather(temperature=temperature), now)
        assert set(result.suitable_species) <= set(ALLOWED_SPECIES)


def test_cold_deep_water_does_not_recommend_warm_water_breeders():
    """鲢鳙/草鱼 are warm-water active feeders; a cold deep profile should not lead."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import compute_fish_activity

    cold = datetime(2026, 1, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = compute_fish_activity(_weather(temperature=3.0, cloud_cover_pct=20), cold)
    assert result.suitable_species[0] == "鲫鱼"
    assert "鲢鳙" not in result.suitable_species


def test_species_and_depth_read_the_same_plan():
    """Warm shallow water can surface warm-water breeders; cold deep water must not.

    The point is not which species win a given case, it is that the species line
    can no longer contradict the depth line: 鲢鳙/草鱼 are warm-water active
    feeders, so a profile the engine describes as deep and cold must not lead
    with them.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fishagent.core.rules import compute_fish_activity

    summer = datetime(2026, 7, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    warm_shallow = compute_fish_activity(
        _weather(temperature=24.0, cloud_cover_pct=85, wind_level=3, wind_speed_ms=4.0),
        summer,
    )
    winter = datetime(2026, 1, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    cold_deep = compute_fish_activity(
        _weather(temperature=8.0, cloud_cover_pct=20, wind_level=3, wind_speed_ms=4.0),
        winter,
    )
    # The warm shallow profile may recommend the active warm-water breeders.
    assert "鲢鳙" in warm_shallow.suitable_species
    # The cold deep profile must not, and must still offer something.
    assert "鲢鳙" not in cold_deep.suitable_species
    assert cold_deep.suitable_species
