"""CR-03 M2: pilot access control, rate limiting and daily upstream quotas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from conftest import fish_params, spot_params
from fastapi.testclient import TestClient

from fishagent.config import get_settings
from fishagent.deps import get_geo_provider, get_weather_provider
from fishagent.main import create_app
from fishagent.pilot import reset_pilot_state
from fishagent.pilot.limits import (
    DailyQuotaLedger,
    QuotaGuardedGeoProvider,
    SlidingWindowLimiter,
)
from fishagent.pilot.tokens import TokenError, TokenSigner
from fishagent.providers.base import UpstreamQuotaExceeded
from fishagent.providers.weather_mock import MockWeatherProvider
from fishagent.schemas import LatLon, SpotCandidate

INVITE_CODE = "pilot-code-123"
TOKEN_SECRET = "0123456789abcdef" * 4
COOKIE_NAME = "fishagent_pilot"

PILOT_ENV = {
    "FISHAGENT_MOCK_MODE": "true",
    "FISHAGENT_PUBLIC_ACCESS_ENABLED": "true",
    "FISHAGENT_PILOT_INVITE_CODE": INVITE_CODE,
    "FISHAGENT_PILOT_TOKEN_SECRET": TOKEN_SECRET,
    "FISHAGENT_PILOT_TOKEN_TTL_SECONDS": "3600",
    "FISHAGENT_PILOT_COOKIE_NAME": COOKIE_NAME,
    "FISHAGENT_PILOT_COOKIE_SECURE": "true",
    "FISHAGENT_PILOT_CORS_ORIGINS": "https://pilot.example.com",
    "FISHAGENT_PILOT_TRUST_PROXY_HEADERS": "false",
    "FISHAGENT_PILOT_RATE_LIMIT_IP_PER_MINUTE": "1000",
    "FISHAGENT_PILOT_RATE_LIMIT_TOKEN_PER_MINUTE": "1000",
    "FISHAGENT_PILOT_LOGIN_ATTEMPTS_PER_MINUTE": "1000",
    "FISHAGENT_AMAP_DAILY_QUOTA": "2000",
    "FISHAGENT_LLM_DAILY_QUOTA": "200",
    "FISHAGENT_OPEN_METEO_DAILY_QUOTA": "1000",
    "FISHAGENT_QUOTA_DAY_TIMEZONE": "Asia/Shanghai",
}


class FakeGeo:
    def __init__(self) -> None:
        self.calls = 0

    async def find_water_spots(
        self,
        origin: LatLon,
        center: LatLon,
        radius_m: int,
    ) -> list[SpotCandidate]:
        self.calls += 1
        return [
            SpotCandidate(
                id="a",
                name="甲河",
                water_type="河流",
                location_gcj02=LatLon(lat=30.30, lon=120.20),
                entry_location_gcj02=LatLon(lat=30.301, lon=120.201),
            ),
            SpotCandidate(
                id="b",
                name="乙湖",
                water_type="湖泊",
                location_gcj02=LatLon(lat=30.31, lon=120.21),
            ),
        ]

    async def estimate_batch_drive_seconds(
        self,
        origin: LatLon,
        destinations: list[LatLon],
    ) -> list[int | None]:
        self.calls += 1
        return [600 for _ in destinations]

    async def estimate_drive_seconds(
        self,
        origin: LatLon,
        destination: LatLon,
        departure_at: datetime,
        direction: str,
        route_key: str = "",
    ) -> int:
        self.calls += 1
        return 600


@pytest.fixture()
def build_app(monkeypatch):
    def build(**overrides: str | None):
        env = {**PILOT_ENV, **overrides}
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        reset_pilot_state()
        return create_app()

    yield build
    reset_pilot_state()
    get_settings.cache_clear()


def login(client: TestClient, code: str = INVITE_CODE):
    return client.post("/api/pilot/login", json={"code": code})


def login_client(client: TestClient) -> None:
    response = login(client)
    assert response.status_code == 200, response.text


def _usage(client: TestClient) -> dict:
    response = client.get("/api/pilot/usage")
    assert response.status_code == 200, response.text
    return response.json()


# --- default (S1) behaviour -------------------------------------------------


def test_pilot_disabled_keeps_s1_behaviour(client, app):
    assert getattr(app.state, "pilot", None) is None
    response = client.get(
        "/api/fish-activity",
        params=fish_params(),
        headers={"Origin": "https://anything.example"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
    assert client.get("/api/pilot/login").status_code == 404
    assert client.get("/pilot/login").status_code == 404


# --- login / token / session ------------------------------------------------


def test_login_page_is_public_and_leaks_no_secret(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/pilot/login")
        assert response.status_code == 200
        assert "邀请码" in response.text
        assert INVITE_CODE not in response.text
        assert TOKEN_SECRET not in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"


def test_protected_endpoints_require_login(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/demo/config").status_code == 200
        session = client.get("/api/pilot/session").json()
        assert session == {"authenticated": False}

        for path in ("/api/fish-activity", "/api/spots/recommend", "/api/agent/chat", "/docs"):
            response = client.get(path) if path != "/api/agent/chat" else client.post(
                path, json={"message": "hi", "location": {"lat": 30.2, "lon": 120.1}}
            )
            assert response.status_code == 401, path
            detail = response.json()["detail"]
            assert detail["code"] == "UNAUTHORIZED"
            assert response.headers["www-authenticate"].startswith("Bearer")


def test_wrong_invite_code_is_rejected(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        response = login(client, "wrong-code")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "INVALID_INVITE_CODE"
        assert "set-cookie" not in response.headers


def test_login_sets_hardened_cookie_and_unlocks_api(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        response = login(client)
        assert response.status_code == 200
        assert set(response.json()) == {"ok", "expires_at"}
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie

        assert client.get("/api/fish-activity", params=fish_params()).status_code == 200
        session = client.get("/api/pilot/session").json()
        assert session["authenticated"] is True
        assert session["expires_at"].endswith("Z")


def test_bearer_token_is_accepted_and_tampering_is_rejected(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        token, _ = app.state.pilot.tokens.issue()
        response = client.get(
            "/api/fish-activity",
            params=fish_params(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"

        tampered = f"{token[:-2]}aa"
        response = client.get(
            "/api/fish-activity",
            params=fish_params(),
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "INVALID_TOKEN"


def test_expired_token_returns_401(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        state = app.state.pilot
        state.tokens.clock = lambda: 1_000_000.0
        login_client(client)
        state.tokens.clock = lambda: 1_000_000.0 + 3601
        response = client.get("/api/fish-activity", params=fish_params())
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


def _assert_401_headers(response, code: str) -> None:
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["www-authenticate"] == 'Bearer realm="fishagent-pilot"'


def test_every_401_code_carries_no_store_and_challenge(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        _assert_401_headers(
            client.get("/api/fish-activity", params=fish_params()),
            "UNAUTHORIZED",
        )
        _assert_401_headers(
            client.get(
                "/api/fish-activity",
                params=fish_params(),
                headers={"Authorization": "Bearer not-a-token"},
            ),
            "INVALID_TOKEN",
        )

        state = app.state.pilot
        state.tokens.clock = lambda: 1_000_000.0
        login_client(client)
        state.tokens.clock = lambda: 1_000_000.0 + 3601
        _assert_401_headers(
            client.get("/api/fish-activity", params=fish_params()),
            "TOKEN_EXPIRED",
        )

        _assert_401_headers(login(client, "wrong-code"), "INVALID_INVITE_CODE")


def test_logout_clears_cookie(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        response = client.post("/api/pilot/logout")
        assert response.status_code == 200
        assert client.get("/api/fish-activity", params=fish_params()).status_code == 401


# --- start-up validation ----------------------------------------------------


def test_enabled_requires_invite_code(build_app):
    with pytest.raises(RuntimeError, match="FISHAGENT_PILOT_INVITE_CODE"):
        build_app(FISHAGENT_PILOT_INVITE_CODE="")


def test_enabled_requires_long_token_secret(build_app):
    with pytest.raises(RuntimeError, match="FISHAGENT_PILOT_TOKEN_SECRET"):
        build_app(FISHAGENT_PILOT_TOKEN_SECRET="short-secret")


def test_cors_wildcard_is_rejected(build_app):
    with pytest.raises(RuntimeError, match="explicit origins"):
        build_app(FISHAGENT_PILOT_CORS_ORIGINS="*")


def test_cors_origin_must_be_origin_only(build_app):
    with pytest.raises(RuntimeError, match="invalid CORS origin"):
        build_app(FISHAGENT_PILOT_CORS_ORIGINS="https://pilot.example.com/app")


# --- CORS whitelist ---------------------------------------------------------


def test_cors_allows_only_whitelisted_origin(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        allowed = client.get(
            "/api/fish-activity",
            params=fish_params(),
            headers={"Origin": "https://pilot.example.com"},
        )
        assert allowed.headers["access-control-allow-origin"] == "https://pilot.example.com"
        assert allowed.headers["access-control-allow-credentials"] == "true"

        blocked = client.get(
            "/api/fish-activity",
            params=fish_params(),
            headers={"Origin": "https://evil.example.com"},
        )
        assert blocked.status_code == 200
        assert "access-control-allow-origin" not in blocked.headers

        preflight = client.options(
            "/api/fish-activity",
            headers={
                "Origin": "https://pilot.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://pilot.example.com"

        denied = client.options(
            "/api/fish-activity",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert denied.status_code == 400


def test_empty_cors_whitelist_means_same_origin_only(build_app):
    app = build_app(FISHAGENT_PILOT_CORS_ORIGINS="")
    with TestClient(app, base_url="https://testserver") as client:
        response = client.options(
            "/api/fish-activity",
            headers={
                "Origin": "https://pilot.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 405
        assert "access-control-allow-origin" not in response.headers


# --- rate limits ------------------------------------------------------------


def test_ip_rate_limit_returns_429(build_app):
    app = build_app(FISHAGENT_PILOT_RATE_LIMIT_IP_PER_MINUTE="2")
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        assert client.get("/api/fish-activity", params=fish_params()).status_code == 200
        assert client.get("/api/fish-activity", params=fish_params()).status_code == 200
        response = client.get("/api/fish-activity", params=fish_params())
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "RATE_LIMITED"
        assert int(response.headers["retry-after"]) >= 1


def test_token_rate_limit_returns_429(build_app):
    app = build_app(FISHAGENT_PILOT_RATE_LIMIT_TOKEN_PER_MINUTE="1")
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        assert client.get("/api/fish-activity", params=fish_params()).status_code == 200
        response = client.get("/api/fish-activity", params=fish_params())
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "RATE_LIMITED"


def test_login_attempts_are_rate_limited(build_app):
    app = build_app(FISHAGENT_PILOT_LOGIN_ATTEMPTS_PER_MINUTE="2")
    with TestClient(app, base_url="https://testserver") as client:
        assert login(client, "wrong").status_code == 401
        assert login(client, "wrong").status_code == 401
        response = login(client, "wrong")
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "RATE_LIMITED"


def test_sliding_window_recovers_after_window():
    now = [100.0]
    limiter = SlidingWindowLimiter(limit=2, clock=lambda: now[0])
    assert limiter.hit("k") is None
    assert limiter.hit("k") is None
    assert limiter.hit("k") == 60
    now[0] += 61
    assert limiter.hit("k") is None


# --- tokens -----------------------------------------------------------------


def test_token_signer_roundtrip_and_failures():
    now = [1_000.0]
    signer = TokenSigner(TOKEN_SECRET, 60, clock=lambda: now[0])
    token, claims = signer.issue()
    verified = signer.verify(token)
    assert verified.expires_at == claims.expires_at == 1_060
    assert verified.subject == "pilot"

    with pytest.raises(TokenError) as invalid:
        signer.verify("v1.not-base64.not-base64")
    assert invalid.value.code == "INVALID_TOKEN"

    with pytest.raises(TokenError) as expired:
        now[0] = 1_061.0
        signer.verify(token)
    assert expired.value.code == "TOKEN_EXPIRED"

    other = TokenSigner("f" * 32, 60, clock=lambda: 1_000.0)
    with pytest.raises(TokenError):
        other.verify(token)


# --- quotas -----------------------------------------------------------------


def test_quota_ledger_blocks_at_limit_and_rolls_over():
    now = [datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)]
    ledger = DailyQuotaLedger(
        {"amap": 2, "open_meteo": 1000, "llm": 200},
        day_timezone="UTC",
        clock=lambda: now[0],
    )
    ledger.consume("amap")
    ledger.consume("amap")
    with pytest.raises(UpstreamQuotaExceeded) as exhausted:
        ledger.consume("amap")
    assert exhausted.value.provider == "amap"
    assert 3_000 <= exhausted.value.retry_after_seconds <= 3_600

    snapshot = ledger.snapshot()
    assert snapshot["providers"]["amap"] == {
        "used": 2,
        "limit": 2,
        "remaining": 0,
        "exhausted": True,
    }

    now[0] = datetime(2026, 10, 25, 0, 0, 1, tzinfo=timezone.utc)
    ledger.consume("amap")
    assert ledger.snapshot()["providers"]["amap"]["used"] == 1


async def test_quota_wrapper_stops_before_upstream_call():
    ledger = DailyQuotaLedger(
        {"amap": 1, "open_meteo": 1, "llm": 1},
        day_timezone="UTC",
    )
    fake = FakeGeo()
    guarded = QuotaGuardedGeoProvider(fake, ledger)
    origin = LatLon(lat=30.27, lon=120.15)

    await guarded.find_water_spots(origin, origin, 20_000)
    with pytest.raises(UpstreamQuotaExceeded):
        await guarded.find_water_spots(origin, origin, 20_000)
    assert fake.calls == 1


def test_quota_exhausted_before_recall_returns_429(build_app):
    app = build_app(FISHAGENT_AMAP_DAILY_QUOTA="0")
    fake = FakeGeo()
    app.dependency_overrides[get_geo_provider] = lambda: QuotaGuardedGeoProvider(
        fake, app.state.pilot.ledger
    )
    app.dependency_overrides[get_weather_provider] = MockWeatherProvider
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        response = client.get("/api/spots/recommend", params=spot_params(radius_km=20))
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "QUOTA_EXCEEDED"
        assert int(response.headers["retry-after"]) >= 1
        assert fake.calls == 0

        amap = _usage(client)["providers"]["amap"]
        assert amap == {"used": 0, "limit": 0, "remaining": 0, "exhausted": True}


def test_quota_exhaustion_mid_request_aborts_with_429(build_app):
    app = build_app(FISHAGENT_AMAP_DAILY_QUOTA="2")
    fake = FakeGeo()
    app.dependency_overrides[get_geo_provider] = lambda: QuotaGuardedGeoProvider(
        fake, app.state.pilot.ledger
    )
    app.dependency_overrides[get_weather_provider] = MockWeatherProvider
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        response = client.get("/api/spots/recommend", params=spot_params(radius_km=20))
        assert response.status_code == 429, response.text
        assert response.json()["detail"]["code"] == "QUOTA_EXCEEDED"
        assert fake.calls == 2

        amap = _usage(client)["providers"]["amap"]
        assert amap["used"] == 2
        assert amap["exhausted"] is True


def test_llm_quota_is_reserved_before_agent_graph(build_app):
    app = build_app(
        FISHAGENT_MOCK_MODE="false",
        LLM_API_KEY="dummy-key",
        LLM_BASE_URL="https://llm.invalid/v1",
        FISHAGENT_LLM_DAILY_QUOTA="0",
        AMAP_WEB_KEY="",
    )
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        response = client.post(
            "/api/agent/chat",
            json={"message": "今天适合钓鱼吗", "location": {"lat": 30.27, "lon": 120.15}},
        )
        assert response.status_code == 429, response.text
        assert response.json()["detail"]["code"] == "QUOTA_EXCEEDED"

        llm = _usage(client)["providers"]["llm"]
        assert llm == {"used": 0, "limit": 0, "remaining": 0, "exhausted": True}


def test_usage_endpoint_requires_login_and_reports_limits(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/pilot/usage").status_code == 401
        login_client(client)
        body = _usage(client)
        assert set(body["providers"]) == {"amap", "open_meteo", "llm"}
        assert body["providers"]["amap"]["limit"] == 2000
        assert body["providers"]["llm"]["limit"] == 200
        assert body["rate_limits"]["ip_per_minute"] == 1000
        assert body["llm_reserved_per_chat"] == 2
        assert INVITE_CODE not in str(body)
        assert TOKEN_SECRET not in str(body)


# --- rotating the two secrets means two different things ---------------------
#
# The invite code is checked once, at login. The token secret signs the cookie
# and is checked on every request. Rotating them is therefore not the same
# operation, and the script that generates them (scripts/gen-pilot-secrets.py)
# exposes that difference as --invite-only. These tests pin the behaviour so a
# future "let's validate the invite code on every request" change cannot land
# silently -- it would turn "issue a new code" into "log everyone out".


def _authenticated(client: TestClient) -> bool:
    """/api/pilot/session is public and always answers 200; it reports the
    verdict in the body. Asserting the status code here would pass no matter
    what the token was."""
    response = client.get("/api/pilot/session")
    assert response.status_code == 200, response.text
    return response.json()["authenticated"]


def test_old_token_still_works_after_the_invite_code_changes(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        token = client.cookies[COOKIE_NAME]

    # Same token secret, different invite code: a session already issued must
    # survive. Otherwise handing out a new code would silently evict pilots.
    new_app = build_app(FISHAGENT_PILOT_INVITE_CODE="a-different-invite-code")
    with TestClient(new_app, base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, token)
        assert _authenticated(client) is True
        # ...while the old code no longer buys a new session.
        assert login(client, INVITE_CODE).status_code == 401
        assert login(client, "a-different-invite-code").status_code == 200


def test_rotating_the_token_secret_revokes_existing_sessions(build_app):
    app = build_app()
    with TestClient(app, base_url="https://testserver") as client:
        login_client(client)
        token = client.cookies[COOKIE_NAME]

    rotated = build_app(FISHAGENT_PILOT_TOKEN_SECRET="another-secret-value-32-bytes-long!!")
    with TestClient(rotated, base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, token)
        assert _authenticated(client) is False
        assert client.get("/api/fish-activity", params=fish_params()).status_code == 401


def test_generator_invite_alphabet_has_no_lookalikes():
    """The code gets read aloud and typed on a phone. 0/O and 1/l/I are the
    whole reason mistyped codes look like wrong codes."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "gen-pilot-secrets.py"
    spec = importlib.util.spec_from_file_location("gen_pilot_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for char in "0O1lI":
        assert char not in module.INVITE_ALPHABET, char
    code = module.make_invite_code()
    assert len(code) == module.INVITE_LENGTH >= module.MIN_INVITE
    assert set(code) <= set(module.INVITE_ALPHABET)
    assert len(module.make_token_secret()) >= module.MIN_SECRET
