"""CR-03 P2 independent retest (O-CR03-01 / O-CR03-02).

O-CR03-01: every 401 code must carry Cache-Control: no-store and
           WWW-Authenticate: Bearer realm="fishagent-pilot".
O-CR03-02: an instance started with --no-access-log must emit zero per-request
           access lines after health + 4x401 + login + business traffic.

Uses only local mock instances; no real provider key or upstream call.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent
REPO = Path(r"D:\学习\GitHubCode\FishAgent")
PYTHON = sys.executable
BASE = "http://127.0.0.1:8022"
NO_LOG_BASE = "http://127.0.0.1:8037"
INVITE = "CR03-C-INVITE-2026"
SECRET = "cr03-c-token-secret-0123456789abcdef0123456789abcdef"
CHALLENGE = 'Bearer realm="fishagent-pilot"'
COOKIE = "fishagent_pilot"
results: list[dict] = []


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def forged_token(exp_offset: int) -> str:
    now = int(time.time())
    payload = json.dumps(
        {"exp": now + exp_offset, "iat": now - 3600, "jti": "cr03p2", "sub": "pilot"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = b64(payload)
    signature = hmac.new(
        SECRET.encode("utf-8"), f"v1.{encoded}".encode("ascii"), hashlib.sha256
    ).digest()
    return f"v1.{encoded}.{b64(signature)}"


def check(cid: str, ok: bool, detail) -> None:
    results.append({"id": cid, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(("PASS " if ok else "FAIL ") + cid + " " + json.dumps(detail, ensure_ascii=False))


def headers_ok(response: requests.Response) -> dict:
    cache = response.headers.get("Cache-Control", "")
    challenge = response.headers.get("WWW-Authenticate", "")
    return {
        "cacheControl": cache,
        "wwwAuthenticate": challenge,
        "noStore": "no-store" in cache.lower(),
        "challengeMatch": challenge == CHALLENGE,
    }


def probe_401(base: str, cid: str, *, cookies=None, token=None, login_code=None) -> requests.Response:
    session = requests.Session()
    jar = {}
    if token is not None:
        jar[COOKIE] = token
    if cookies:
        jar.update(cookies)
    if jar:
        session.cookies.update(jar)
    if login_code is not None:
        return session.post(base + "/api/pilot/login", json={"code": login_code}, timeout=15)
    return session.get(
        base + "/api/fish-activity",
        params={"lat": 30.657, "lon": 104.066},
        timeout=15,
    )


def matrix(base: str, prefix: str) -> None:
    cases = [
        ("UNAUTHORIZED", dict(token=None)),
        ("INVALID_TOKEN", dict(token="v1.bad.bad")),
        ("TOKEN_EXPIRED", dict(token=forged_token(-120))),
        ("INVALID_INVITE_CODE", dict(login_code="WRONG-INVITE")),
    ]
    for expected, kwargs in cases:
        response = probe_401(base, expected, **kwargs)
        try:
            code = response.json().get("detail", {}).get("code")
        except ValueError:
            code = None
        hdr = headers_ok(response)
        check(
            f"{prefix}-{expected}-headers",
            response.status_code == 401 and code == expected and hdr["noStore"] and hdr["challengeMatch"],
            {"status": response.status_code, "code": code, **hdr},
        )


def start_no_access_log() -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO / "backend"),
            "FISHAGENT_MOCK_MODE": "true",
            "FISHAGENT_PUBLIC_ACCESS_ENABLED": "true",
            "FISHAGENT_PILOT_INVITE_CODE": INVITE,
            "FISHAGENT_PILOT_TOKEN_SECRET": SECRET,
            "FISHAGENT_PILOT_COOKIE_SECURE": "false",
        }
    )
    log = (OUT / "p2-noaccess-8037.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "fishagent.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8037",
            "--workers",
            "1",
            "--no-access-log",
        ],
        cwd=str(REPO),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(100):
        try:
            if requests.get(NO_LOG_BASE + "/health", timeout=0.5).status_code == 200:
                return proc
        except requests.RequestException:
            pass
        time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("8037 did not become ready")


def main() -> None:
    matrix(BASE, "P2a-8022")

    plan = (REPO / "docs" / "cr03-deployment-plan.md").read_text(encoding="utf-8")
    start_line = next((ln for ln in plan.splitlines() if "uvicorn fishagent.main:app" in ln), "")
    check(
        "P2b-plan-startup-command",
        "--no-access-log" in start_line and "--workers 1" in start_line,
        {"line": start_line.strip()},
    )
    check(
        "P2b-plan-section-3.1",
        "### 3.1" in plan and "O-CR03-02" in plan and "X-Forwarded-For" in plan,
        {"has31": "### 3.1" in plan, "mentionsXFF": "X-Forwarded-For" in plan},
    )

    proc = start_no_access_log()
    try:
        traffic = [
            ("health", requests.get(NO_LOG_BASE + "/health", timeout=10)),
            ("unauthorized", probe_401(NO_LOG_BASE, "UNAUTHORIZED")),
            ("invalid-token", probe_401(NO_LOG_BASE, "INVALID_TOKEN", token="v1.bad.bad")),
            ("expired-token", probe_401(NO_LOG_BASE, "TOKEN_EXPIRED", token=forged_token(-120))),
            ("bad-invite", probe_401(NO_LOG_BASE, "INVALID_INVITE_CODE", login_code="WRONG-INVITE")),
        ]
        statuses = [(name, r.status_code) for name, r in traffic]
        check(
            "P2b-401-headers-on-no-log-instance",
            all(
                headers_ok(r)["noStore"] and headers_ok(r)["challengeMatch"]
                for name, r in traffic
                if name != "health"
            ),
            {name: headers_ok(r) for name, r in traffic if name != "health"},
        )
        check(
            "P2b-traffic-statuses",
            statuses == [
                ("health", 200),
                ("unauthorized", 401),
                ("invalid-token", 401),
                ("expired-token", 401),
                ("bad-invite", 401),
            ],
            statuses,
        )

        session = requests.Session()
        login = session.post(NO_LOG_BASE + "/api/pilot/login", json={"code": INVITE}, timeout=15)
        activity = session.get(
            NO_LOG_BASE + "/api/fish-activity",
            params={"lat": 30.657, "lon": 104.066},
            timeout=15,
        )
        spots = session.get(
            NO_LOG_BASE + "/api/spots/recommend",
            params={"lat": 30.657, "lon": 104.066, "radius_km": 50, "limit": 10},
            timeout=15,
        )
        check(
            "P2b-login-and-business",
            login.status_code == 200
            and bool(session.cookies.get(COOKIE))
            and activity.status_code == 200
            and spots.status_code == 200,
            {"login": login.status_code, "activity": activity.status_code, "spots": spots.status_code},
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    log_text = (OUT / "p2-noaccess-8037.log").read_text(encoding="utf-8", errors="replace")
    access_lines = [ln for ln in log_text.splitlines() if "HTTP/1.1" in ln]
    startup_lines = [ln for ln in log_text.splitlines() if ln.startswith("INFO:")]
    check(
        "P2b-no-access-log-lines",
        len(access_lines) == 0 and len(startup_lines) >= 4,
        {"requests": 8, "accessLines": len(access_lines), "startupLines": len(startup_lines)},
    )

    try:
        health = requests.get("http://127.0.0.1:8018/health", timeout=3)
        check(
            "P2c-8018-health-only",
            health.status_code == 200,
            {"status": health.status_code, "body": health.json()},
        )
    except requests.RequestException as exc:
        check("P2c-8018-health-only", False, {"error": str(exc)})

    passed = sum(1 for r in results if r["status"] == "PASS")
    summary = {"total": len(results), "passed": passed, "results": results}
    (OUT / "cr03-p2-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"TOTAL {passed}/{len(results)} passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
