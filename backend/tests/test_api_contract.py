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


def test_service_worker_does_not_pin_clients_to_stale_assets(client):
    """Installed phones must be able to receive a new release.

    Regression: without skipWaiting the new worker waited for every tab to
    close, and the cache-first static handler never re-fetched app.js, so a
    mobile client kept running the previous build (missing the species line).
    """
    sw = client.get("/sw.js").text
    assert "skipWaiting" in sw, "service worker must activate without waiting"
    assert "clients.claim" in sw

    app_js = client.get("/app.js").text
    assert "推荐鱼种" in app_js, "served app.js must render the species line"


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


def test_unknown_api_route_reports_404_for_post_too(client):
    """A POST to a missing route must say NOT_FOUND, not "Method Not Allowed".

    Regression: the catch-all used to be GET-only, so an unmatched POST fell
    through to the StaticFiles mount and answered a bare 405, which hid the real
    cause (the route never existed).
    """
    response = client.post("/api/definitely-not-a-route", json={})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_wrong_method_on_existing_route_still_reports_405(client):
    """The verb really is wrong here, so 405 remains the honest answer."""
    response = client.get("/api/spots/species")
    assert response.status_code == 405
    assert response.json()["detail"]["code"] == "METHOD_NOT_ALLOWED"


def test_generated_at_is_utc(client):
    response = client.get("/api/fish-activity", params=fish_params(scenario="fair"))
    assert response.status_code == 200
    payload = response.json()
    assert_iso_utc(payload["generated_at"])
    assert payload["timezone"] == "Asia/Shanghai"
