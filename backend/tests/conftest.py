from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# QA runs are deterministic and must never touch real providers. These are set
# before any settings import so a developer's backend/.env cannot leak in and
# make the suite query live search engines.
os.environ["FISHAGENT_MOCK_MODE"] = "true"
os.environ["AMAP_WEB_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["FISHAGENT_SPECIES_PROVIDER"] = ""
os.environ["FISHAGENT_SPECIES_PAGE_FETCH"] = "false"

HANGZHOU = {"lat": 30.2741, "lon": 120.1551}
BEIJING = {"lat": 39.915, "lon": 116.404}
AT_UTC = "2026-10-21T10:00:00Z"

SCENARIOS = {
    "excellent": {"band": "极佳", "min": 85, "max": 100, "advice": "强烈建议出钓"},
    "good": {"band": "良好", "min": 70, "max": 84, "advice": "适合出钓"},
    "fair": {"band": "一般", "min": 55, "max": 69, "advice": "有机会，建议挑时段"},
    "poor": {"band": "偏差", "min": 40, "max": 54, "advice": "不太理想，建议就近作钓"},
    "no_go": {"band": "劝退", "min": 0, "max": 39, "advice": "今天不建议出钓"},
}

PRD_AT_SEEDS = {
    "2026-04-11T21:30:00Z": "极佳",
    "2026-04-13T00:00:00Z": "良好",
    "2026-04-14T02:00:00Z": "一般",
    "2026-04-15T04:00:00Z": "偏差",
    "2026-06-20T06:00:00Z": "劝退",
}

VALID_SPECIES = ["鲫鱼", "鲤鱼", "草鱼", "鲢鳙"]

FACTOR_MAX = {"F1": 25, "F2": 20, "F3": 15, "F4": 15, "F5": 10, "F6": 10, "F7": 5}

PROMISE_PATTERNS = ("必上鱼", "保证爆护", "百分百", "100%", "绝不空军")
FORBIDDEN_SPOT_WORDS = ("一级保护区", "饮用水源", "禁钓", "养殖场", "承包塘")


@pytest.fixture(scope="session")
def app():
    try:
        from fishagent.main import app as fastapi_app
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "fishagent" or exc.name.startswith("fishagent.")):
            pytest.fail(
                "backend/fishagent 尚未交付：Q-02 需在小钱交付后端后执行 "
                "(cd backend && python -m pytest tests -q)"
            )
        raise
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def fish_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {**HANGZHOU, "at": AT_UTC}
    params.update(overrides)
    return params


def spot_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = dict(HANGZHOU)
    params.update(overrides)
    return params


def assert_unified_error(response, expected_status: int = 422, code: str | None = None) -> dict:
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert isinstance(body, dict) and "detail" in body, f"missing detail: {body}"
    detail = body["detail"]
    assert isinstance(detail, dict), f"error detail must be an object, got {type(detail)}: {detail}"
    assert isinstance(detail.get("code"), str) and detail["code"], f"missing code: {detail}"
    assert isinstance(detail.get("message"), str) and detail["message"], (
        f"missing message: {detail}"
    )
    if code is not None:
        assert detail["code"] == code, f"expected code {code}, got {detail['code']}"
    return detail


def assert_iso_utc(value: str) -> None:
    assert isinstance(value, str) and value, "timestamp must be a non-empty string"
    assert value.endswith("Z"), f"timestamp must be UTC with Z suffix: {value}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() == timedelta(0)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def navigation_position(url: str) -> tuple[float, float]:
    parsed = urlparse(url)
    assert parsed.scheme == "https", f"navigation_url must be https: {url}"
    assert parsed.netloc == "uri.amap.com", f"unexpected navigation host: {parsed.netloc}"
    query = parse_qs(parsed.query)
    assert "position" in query and "name" in query, f"navigation_url missing position/name: {url}"
    lon_text, lat_text = query["position"][0].split(",", 1)
    return float(lat_text), float(lon_text)
