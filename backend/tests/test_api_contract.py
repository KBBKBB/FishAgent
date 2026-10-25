from __future__ import annotations

from conftest import assert_iso_utc, assert_unified_error, fish_params


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["mock_mode"] is True


def test_required_routes_are_registered(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in (
        "/health",
        "/api/fish-activity",
        "/api/spots/recommend",
        "/api/spots/species",
        "/api/agent/chat",
    ):
        assert path in paths, f"missing route: {path}"


def test_static_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text
    for text in ("FishAgent", "AI 生成", "免责声明", "不承诺渔获", "Mock 模式"):
        assert text in html, f"missing required UI text: {text}"


def test_static_assets_are_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200


def test_api_route_is_not_shadowed_by_static_mount(client):
    response = client.get("/api/fish-activity", params=fish_params())
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    assert "score" in response.json()


def test_validation_error_uses_unified_shape(client):
    response = client.get("/api/fish-activity", params={"lat": 91, "lon": 120.1551})
    detail = assert_unified_error(response, 422, "VALIDATION_ERROR")
    if "fields" in detail:
        assert isinstance(detail["fields"], list)


def test_unknown_api_route_uses_unified_shape(client):
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    body = response.json()
    assert isinstance(body.get("detail"), dict), f"non-unified 404 body: {body}"
    assert body["detail"].get("code") and body["detail"].get("message")


def test_generated_at_is_utc(client):
    response = client.get("/api/fish-activity", params=fish_params(scenario="fair"))
    assert response.status_code == 200
    payload = response.json()
    assert_iso_utc(payload["generated_at"])
    assert payload["timezone"] == "Asia/Shanghai"
