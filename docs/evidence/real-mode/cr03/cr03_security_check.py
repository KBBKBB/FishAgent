"""CR-03 B: independent local security checks for pilot access control.

Isolated instances only:
  8022: mock mode + public access + tuned limits (IP 8, token 4, login 3)
  8034: non-mock, fake keys, all daily quotas 0, upstream URLs -> local guard :8099
No real provider key and no real upstream call is used.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8022"
QUOTA_BASE = "http://127.0.0.1:8034"
INVITE = "CR03-QA-INVITE-9F2C7A"
SECRET = "cr03-qa-token-secret-0123456789abcdef0123456789abcdef"
COOKIE = "fishagent_pilot"
ALLOWED = "http://allowed.example"
DENIED = "http://evil.example"
LIMIT_IP = 8
LIMIT_TOKEN = 4
LIMIT_LOGIN = 3
LEAK_MARKER = "CR03-INVITE-LEAK-MARKER"

results: list[dict] = []
tokens: dict[str, str] = {}


def check(cid: str, ok: bool, detail=None) -> None:
    results.append({"id": cid, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), cid, "" if detail is None else str(detail)[:400])


def call(method: str, path: str, base: str = BASE, *, xff: str | None = None,
         token: str | None = None, origin: str | None = None, body=None,
         extra_headers=None):
    headers = {"User-Agent": "cr03-qa"}
    if xff:
        headers["X-Forwarded-For"] = xff
    if token:
        headers["Authorization"] = "Bearer " + token
    if origin:
        headers["Origin"] = origin
    if extra_headers:
        headers.update(extra_headers)
    return requests.request(
        method, base + path, headers=headers, json=body, timeout=15, allow_redirects=False
    )


def error_code(resp) -> str:
    try:
        data = resp.json()
        detail = data.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("code", ""))
        if isinstance(detail, str):
            return detail
    except Exception:
        pass
    return ""


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def login(code: str, xff: str, base: str = BASE):
    resp = call("POST", "/api/pilot/login", base=base, xff=xff, body={"code": code})
    cookie = resp.headers.get("set-cookie", "")
    match = re.search(COOKIE + r"=([^;]+)", cookie)
    return resp, (match.group(1) if match else None), cookie


def make_expired_token() -> str:
    now = int(time.time())
    payload = json.dumps(
        {"sub": "pilot", "iat": now - 7200, "exp": now - 3600, "jti": "cr03qaexpired"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = b64(payload)
    sig = hmac.new(SECRET.encode(), f"v1.{encoded}".encode(), hashlib.sha256).digest()
    return f"v1.{encoded}.{b64(sig)}"


def auth_checks() -> None:
    resp = requests.get(BASE + "/pilot/login", timeout=10)
    csp = resp.headers.get("content-security-policy", "")
    check(
        "B01-login-page-headers",
        resp.status_code == 200
        and resp.headers.get("x-frame-options") == "DENY"
        and resp.headers.get("cache-control") == "no-store"
        and "default-src 'none'" in csp
        and "frame-ancestors 'none'" in csp
        and "form-action 'self'" in csp,
        {"status": resp.status_code, "xfo": resp.headers.get("x-frame-options"), "cache": resp.headers.get("cache-control"), "csp": csp},
    )
    external = re.findall(r'(?:src|href)="https?://[^"]+"', resp.text, re.I)
    check("B02-login-page-no-external-assets", not external and INVITE not in resp.text, external or "no external URLs")

    for label, path in (
        ("shell", "/"),
        ("manifest", "/manifest.webmanifest"),
        ("service-worker", "/sw.js"),
        ("health", "/health"),
        ("demo-config", "/api/demo/config"),
    ):
        r = requests.get(BASE + path, timeout=10)
        check(f"B03-public-{label}", r.status_code == 200, r.status_code)

    for label, path in (
        ("fish-activity", "/api/fish-activity?lat=30.657&lon=104.066"),
        ("usage", "/api/pilot/usage"),
        ("openapi", "/openapi.json"),
        ("docs", "/docs"),
    ):
        r = call("GET", path, xff="10.0.0.20")
        check(
            f"B04-no-token-{label}",
            r.status_code == 401 and error_code(r) == "UNAUTHORIZED"
            and r.headers.get("www-authenticate", "").startswith("Bearer")
            and r.headers.get("cache-control") == "no-store",
            {"status": r.status_code, "code": error_code(r), "www": r.headers.get("www-authenticate"), "cache": r.headers.get("cache-control")},
        )

    r = call("GET", "/api/pilot/usage", xff="10.0.0.21", token="not-a-token")
    check("B05-malformed-token", r.status_code == 401 and error_code(r) == "INVALID_TOKEN", {"status": r.status_code, "code": error_code(r)})

    r = call("GET", "/api/pilot/usage", xff="10.0.0.22", token=make_expired_token())
    check(
        "B06-expired-token",
        r.status_code == 401 and error_code(r) == "TOKEN_EXPIRED"
        and r.headers.get("www-authenticate", "").startswith("Bearer")
        and r.headers.get("cache-control") == "no-store",
        {"status": r.status_code, "code": error_code(r), "www": r.headers.get("www-authenticate"), "cache": r.headers.get("cache-control")},
    )

    resp, token, cookie = login(INVITE, "10.0.0.10")
    tokens["main"] = token or ""
    check(
        "B07-correct-invite",
        resp.status_code == 200 and resp.json().get("ok") is True and token is not None
        and token not in resp.text and "expires_at" in resp.json(),
        {"status": resp.status_code, "body": resp.json(), "tokenInBody": token in resp.text if token else None},
    )
    check(
        "B08-cookie-flags",
        all(flag.lower() in cookie.lower() for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=43200")),
        cookie,
    )

    bad = call("POST", "/api/pilot/login", xff="10.0.0.11", body={"code": LEAK_MARKER})
    check(
        "B09-wrong-invite",
        bad.status_code == 401 and error_code(bad) == "INVALID_INVITE_CODE" and "set-cookie" not in bad.headers,
        {"status": bad.status_code, "code": error_code(bad), "cache": bad.headers.get("cache-control"), "www": bad.headers.get("www-authenticate")},
    )
    check(
        "B09b-login-error-no-store",
        bad.headers.get("cache-control") == "no-store",
        {"cache-control": bad.headers.get("cache-control")},
    )
    check(
        "B09c-login-error-www-authenticate",
        bad.headers.get("www-authenticate", "").startswith("Bearer"),
        {"www-authenticate": bad.headers.get("www-authenticate")},
    )

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    r = call("GET", "/api/pilot/usage", xff="10.0.0.23", token=tampered)
    check("B10-tampered-token", r.status_code == 401 and error_code(r) == "INVALID_TOKEN", {"status": r.status_code, "code": error_code(r)})

    r = call("GET", "/api/pilot/usage", xff="10.0.0.24", token=token)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    providers = body.get("providers", {})
    check(
        "B11-usage-authenticated",
        r.status_code == 200 and r.headers.get("cache-control") == "no-store"
        and set(providers) == {"amap", "open_meteo", "llm"}
        and body.get("rate_limits") == {"ip_per_minute": LIMIT_IP, "token_per_minute": LIMIT_TOKEN, "login_per_minute": LIMIT_LOGIN}
        and body.get("llm_reserved_per_chat") == 2
        and body.get("timezone") == "Asia/Shanghai",
        {"status": r.status_code, "body": body},
    )

    sess = call("GET", "/api/pilot/session", xff="10.0.0.25", token=token)
    sess_body = sess.json() if sess.status_code == 200 else {}
    check(
        "B12-session-authenticated",
        sess.status_code == 200 and sess_body.get("authenticated") is True and "expires_at" in sess_body,
        sess_body,
    )
    anon = call("GET", "/api/pilot/session", xff="10.0.0.26")
    check("B13-session-anonymous", anon.status_code == 200 and anon.json().get("authenticated") is False, anon.json())

    out = call("POST", "/api/pilot/logout", xff="10.0.0.27")
    check(
        "B14-logout-clears-cookie",
        out.status_code == 200 and "Max-Age=0" in out.headers.get("set-cookie", ""),
        {"status": out.status_code, "set-cookie": out.headers.get("set-cookie")},
    )


def rate_limit_checks() -> None:
    # login attempts: 3 allowed, 4th blocked
    codes = []
    retry_after = None
    for i in range(LIMIT_LOGIN + 1):
        r = call("POST", "/api/pilot/login", xff="10.0.0.40", body={"code": LEAK_MARKER})
        codes.append((r.status_code, error_code(r)))
        if i == LIMIT_LOGIN:
            retry_after = r.headers.get("retry-after")
    check(
        "B15-login-rate-limit",
        [c[0] for c in codes[:LIMIT_LOGIN]] == [401] * LIMIT_LOGIN
        and codes[LIMIT_LOGIN][0] == 429 and codes[LIMIT_LOGIN][1] == "RATE_LIMITED"
        and retry_after and 1 <= int(retry_after) <= 60,
        {"sequence": codes, "retryAfter": retry_after},
    )

    # token limit: fresh token fingerprint, 4 allowed, 5th blocked
    _, rate_token, _ = login(INVITE, "10.0.0.43")
    statuses = []
    retry_after = None
    for i in range(LIMIT_TOKEN + 1):
        r = call("GET", "/api/pilot/usage", xff="10.0.0.41", token=rate_token)
        statuses.append((r.status_code, error_code(r)))
        if i == LIMIT_TOKEN:
            retry_after = r.headers.get("retry-after")
            body = r.json()
    check(
        "B16-token-rate-limit",
        [s[0] for s in statuses[:LIMIT_TOKEN]] == [200] * LIMIT_TOKEN
        and statuses[LIMIT_TOKEN][0] == 429 and statuses[LIMIT_TOKEN][1] == "RATE_LIMITED"
        and retry_after and 1 <= int(retry_after) <= 60,
        {"sequence": statuses, "retryAfter": retry_after, "body": body},
    )

    # IP limit: 8 allowed (401), 9th blocked
    statuses = []
    retry_after = None
    for i in range(LIMIT_IP + 1):
        r = call("GET", "/api/fish-activity?lat=30.657&lon=104.066", xff="10.0.0.42")
        statuses.append((r.status_code, error_code(r)))
        if i == LIMIT_IP:
            retry_after = r.headers.get("retry-after")
    check(
        "B17-ip-rate-limit",
        [s[0] for s in statuses[:LIMIT_IP]] == [401] * LIMIT_IP
        and statuses[LIMIT_IP][0] == 429 and statuses[LIMIT_IP][1] == "RATE_LIMITED"
        and retry_after and 1 <= int(retry_after) <= 60,
        {"sequence": statuses, "retryAfter": retry_after},
    )


def cors_checks() -> None:
    _, cors_token, _ = login(INVITE, "10.0.0.54")
    pre = requests.options(
        BASE + "/api/spots/recommend",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
            "X-Forwarded-For": "10.0.0.50",
        },
        timeout=10,
    )
    check(
        "B18-cors-preflight-allowed",
        pre.status_code in (200, 204)
        and pre.headers.get("access-control-allow-origin") == ALLOWED
        and pre.headers.get("access-control-allow-credentials") == "true"
        and "GET" in pre.headers.get("access-control-allow-methods", ""),
        {"status": pre.status_code, "acao": pre.headers.get("access-control-allow-origin"), "acac": pre.headers.get("access-control-allow-credentials"), "methods": pre.headers.get("access-control-allow-methods")},
    )

    r = call("GET", "/api/pilot/usage", xff="10.0.0.51", token=cors_token, origin=ALLOWED)
    check(
        "B19-cors-allowed-actual-response",
        r.status_code == 200
        and r.headers.get("access-control-allow-origin") == ALLOWED
        and r.headers.get("access-control-allow-credentials") == "true"
        and "Retry-After" in r.headers.get("access-control-expose-headers", ""),
        {"acao": r.headers.get("access-control-allow-origin"), "expose": r.headers.get("access-control-expose-headers")},
    )

    denied = requests.options(
        BASE + "/api/spots/recommend",
        headers={
            "Origin": DENIED,
            "Access-Control-Request-Method": "GET",
            "X-Forwarded-For": "10.0.0.52",
        },
        timeout=10,
    )
    check(
        "B20-cors-preflight-denied",
        denied.status_code == 400 and not denied.headers.get("access-control-allow-origin"),
        {"status": denied.status_code, "acao": denied.headers.get("access-control-allow-origin")},
    )

    denied_actual = call("GET", "/api/pilot/usage", xff="10.0.0.53", token=cors_token, origin=DENIED)
    check(
        "B21-cors-denied-actual-response",
        denied_actual.status_code == 200 and not denied_actual.headers.get("access-control-allow-origin"),
        {"status": denied_actual.status_code, "acao": denied_actual.headers.get("access-control-allow-origin")},
    )


def quota_checks() -> None:
    health = requests.get(QUOTA_BASE + "/health", timeout=10).json()
    check("B22-quota-instance-non-mock", health.get("mock_mode") is False, health)
    resp, token, _ = login(INVITE, "10.0.1.10", base=QUOTA_BASE)
    check("B22b-quota-instance-login", resp.status_code == 200 and token is not None, resp.status_code)
    if not token:
        return
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    expected = int((tomorrow - now).total_seconds())

    def quota_call(cid, method, path, body=None):
        r = call(method, path, base=QUOTA_BASE, xff="10.0.1.11", token=token, body=body)
        ra = r.headers.get("retry-after")
        ok = (
            r.status_code == 429
            and error_code(r) == "QUOTA_EXCEEDED"
            and r.headers.get("cache-control") == "no-store"
            and ra is not None and abs(int(ra) - expected) <= 5
            and r.elapsed.total_seconds() < 5
        )
        check(cid, ok, {"status": r.status_code, "code": error_code(r), "retryAfter": ra, "expectedRetryAfter": expected, "seconds": round(r.elapsed.total_seconds(), 3), "body": r.text[:160]})
        return r

    quota_call("B23-quota-open-meteo-429", "GET", "/api/fish-activity?lat=30.657&lon=104.066")
    quota_call("B24-quota-amap-429", "GET", "/api/spots/recommend?lat=30.657&lon=104.066&radius_km=50&limit=10")
    quota_call(
        "B25-quota-llm-429",
        "POST",
        "/api/agent/chat",
        body={"message": "今天适合钓鱼吗", "location": {"lat": 30.657, "lon": 104.066, "name": "成都"}, "session_id": "cr03-qa"},
    )

    usage = call("GET", "/api/pilot/usage", base=QUOTA_BASE, xff="10.0.1.12", token=token)
    body = usage.json() if usage.status_code == 200 else {}
    providers = body.get("providers", {})
    exhausted = {name: bool(providers.get(name, {}).get("exhausted")) for name in ("amap", "open_meteo", "llm")}
    check(
        "B26-usage-after-quota",
        usage.status_code == 200 and all(exhausted.values())
        and all(providers[n]["used"] == 0 and providers[n]["remaining"] == 0 for n in exhausted),
        {"status": usage.status_code, "providers": providers},
    )

    guard = (OUT / "upstream-guard-8099.log").read_text(encoding="utf-8")
    check("B27-no-upstream-connections", "CONNECT" not in guard, guard.strip())


def log_redaction_checks() -> None:
    text = (OUT / "security-instance-8022.log").read_text(encoding="utf-8", errors="replace")
    token = tokens.get("main", "")
    app_lines = [ln for ln in text.splitlines() if not re.match(r'^INFO:\s+127\.0\.0\.1:', ln)]
    check(
        "B28-app-log-no-secrets",
        INVITE not in text and LEAK_MARKER not in text and SECRET not in text
        and (not token or token not in text)
        and "fake-amap-key" not in text and "fake-llm-key" not in text,
        {"inviteLeaked": INVITE in text, "markerLeaked": LEAK_MARKER in text, "secretLeaked": SECRET in text, "tokenLeaked": bool(token and token in text)},
    )
    check(
        "B29-app-log-no-client-ip",
        not any("10.0.0." in ln or "10.0.1." in ln for ln in text.splitlines()),
        "forwarded client IPs absent",
    )
    access_ip_lines = [ln for ln in text.splitlines() if "127.0.0.1:" in ln and '"' in ln]
    check(
        "B30-access-log-peer-ip-observation",
        bool(access_ip_lines),
        {"note": "uvicorn default access log records the socket peer 127.0.0.1; no token/code/key and no forwarded client IP. Deployment guidance: disable/reduce access log if IP must not be retained.", "sample": access_ip_lines[:2]},
    )

    quota_text = (OUT / "quota-instance-8034.log").read_text(encoding="utf-8", errors="replace")
    check(
        "B31-quota-log-no-secrets",
        INVITE not in quota_text and SECRET not in quota_text
        and "fake-amap-key" not in quota_text and "fake-llm-key" not in quota_text
        and (not token or token not in quota_text),
        quota_text.splitlines()[:6],
    )


def state_8018_checks() -> None:
    import subprocess

    netstat = subprocess.run(
        ["C:/Windows/System32/netstat.exe", "-ano"], capture_output=True, text=True, errors="replace"
    ).stdout
    line = next((ln for ln in netstat.splitlines() if ":8018" in ln and "LISTENING" in ln), "")
    check("B32-8018-pid-unchanged", "70828" in line, line.strip())

    probe = [
        ("login-page", "/pilot/login", 404),
        ("session-api", "/api/pilot/session", 404),
        ("usage-api", "/api/pilot/usage", 404),
        ("openapi-no-auth", "/openapi.json", 200),
        ("docs-no-auth", "/docs", 200),
    ]
    observed = {}
    ok = True
    for label, path, expected in probe:
        r = requests.get("http://127.0.0.1:8018" + path, timeout=10)
        observed[label] = r.status_code
        ok = ok and r.status_code == expected
    check("B33-8018-access-control-off", ok, observed)


def fail_closed_checks() -> None:
    import subprocess

    py = "C:/Users/koubinbin/AppData/Local/Programs/Python/Python312/python.exe"
    env = {
        **__import__("os").environ,
        "FISHAGENT_MOCK_MODE": "true",
        "FISHAGENT_PUBLIC_ACCESS_ENABLED": "true",
        "FISHAGENT_PILOT_INVITE_CODE": "",
        "FISHAGENT_PILOT_TOKEN_SECRET": "",
    }
    proc = subprocess.run(
        [py, "-m", "uvicorn", "fishagent.main:app", "--host", "127.0.0.1", "--port", "8036"],
        cwd=r"D:\学习\GitHubCode\FishAgent\backend",
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    check(
        "B34-fail-closed-missing-secrets",
        proc.returncode != 0 and "FISHAGENT_PILOT_INVITE_CODE" in output,
        {"returncode": proc.returncode, "tail": output.strip().splitlines()[-3:]},
    )

    env2 = {
        **__import__("os").environ,
        "FISHAGENT_MOCK_MODE": "true",
        "FISHAGENT_PUBLIC_ACCESS_ENABLED": "true",
        "FISHAGENT_PILOT_INVITE_CODE": "CR03-QA-INVITE-9F2C7A",
        "FISHAGENT_PILOT_TOKEN_SECRET": SECRET,
        "FISHAGENT_PILOT_CORS_ORIGINS": "*",
    }
    proc2 = subprocess.run(
        [py, "-m", "uvicorn", "fishagent.main:app", "--host", "127.0.0.1", "--port", "8036"],
        cwd=r"D:\学习\GitHubCode\FishAgent\backend",
        env=env2,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    output2 = (proc2.stdout or "") + (proc2.stderr or "")
    check(
        "B35-fail-closed-wildcard-cors",
        proc2.returncode != 0 and "must list explicit origins" in output2,
        {"returncode": proc2.returncode, "tail": output2.strip().splitlines()[-3:]},
    )


def main() -> int:
    auth_checks()
    rate_limit_checks()
    cors_checks()
    quota_checks()
    log_redaction_checks()
    state_8018_checks()
    fail_closed_checks()

    passed = sum(1 for r in results if r["ok"])
    summary = {
        "base_mock_auth": BASE,
        "base_quota": QUOTA_BASE,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "failures": [r for r in results if not r["ok"]],
        "results": results,
    }
    (OUT / "cr03-security-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTOTAL {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
