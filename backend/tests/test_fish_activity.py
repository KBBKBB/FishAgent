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
