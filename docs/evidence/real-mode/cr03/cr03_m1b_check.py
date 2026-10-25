"""CR-03 C: independent integration checks for H5 401/429 handling (M1b).

Isolated instances:
  8022: mock + access control, normal limits  -> 401 redirects, login, normal path
  8036: mock + access control, token limit 1  -> RATE_LIMITED
  8034: non-mock + fake keys, quotas 0        -> QUOTA_EXCEEDED (no upstream)
No real provider key or upstream call is used; 8099 guard records any attempt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from pathlib import Path

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8022"
RATE = "http://127.0.0.1:8036"
QUOTA = "http://127.0.0.1:8034"
INVITE = "CR03-C-INVITE-2026"
SECRET = "cr03-c-token-secret-0123456789abcdef0123456789abcdef"
UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
UA_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
FORBIDDEN = (
    "禁钓提示：国家公园、自然保护区、饮用水水源保护区等保护地禁止垂钓；"
    "其他水域是否可钓以当地公告为准。"
)

results: list[dict] = []


def check(cid: str, ok: bool, detail=None) -> None:
    results.append({"id": cid, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), cid, "" if detail is None else str(detail)[:360])


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def forged_token(exp_offset: int) -> str:
    now = int(time.time())
    payload = json.dumps(
        {"exp": now + exp_offset, "iat": now - 3600, "jti": "cr03cqa", "sub": "pilot"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = b64(payload)
    signature = hmac.new(
        SECRET.encode("utf-8"), f"v1.{encoded}".encode("ascii"), hashlib.sha256
    ).digest()
    return f"v1.{encoded}.{b64(signature)}"


def login_api(base: str = BASE) -> str:
    response = requests.post(base + "/api/pilot/login", json={"code": INVITE}, timeout=15)
    token = response.cookies.get("fishagent_pilot")
    if response.status_code != 200 or not token:
        raise RuntimeError(f"login failed on {base}: {response.status_code}")
    return token


def add_cookie(context, base: str, value: str) -> None:
    context.add_cookies(
        [
            {
                "name": "fishagent_pilot",
                "value": value,
                "url": base + "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )


class Tracker:
    def __init__(self, page) -> None:
        self.responses: list[dict] = []
        self.requests: list[dict] = []
        self.console: list[str] = []
        self.pageerrors: list[str] = []
        self.navigations: list[str] = []
        page.on("response", self._response)
        page.on("request", self._request)
        page.on("console", self._console)
        page.on("pageerror", lambda err: self.pageerrors.append(str(err)))
        page.on("framenavigated", lambda frame: self.navigations.append(frame.url))

    def _response(self, response) -> None:
        self.responses.append(
            {
                "url": response.url,
                "status": response.status,
                "headers": dict(response.headers),
                "t": time.time(),
            }
        )

    def _request(self, request) -> None:
        self.requests.append({"url": request.url, "t": time.time()})

    def _console(self, message) -> None:
        if message.type == "error":
            self.console.append(message.text)


def new_page(browser, *, viewport, ua: str | None = None, block_sw: bool = False):
    kwargs = {"viewport": viewport}
    if ua:
        kwargs["user_agent"] = ua
    if block_sw:
        kwargs["service_workers"] = "block"
    context = browser.new_context(**kwargs)
    page = context.new_page()
    return context, page, Tracker(page)


def goto_shell(page, url: str) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except PlaywrightError:
        pass


def wait_spots(page, min_count: int = 1) -> None:
    page.wait_for_function(
        "n => document.querySelectorAll('#spots-body .spot').length >= n", arg=min_count, timeout=20000
    )
    page.wait_for_function(
        "() => document.getElementById('spots-body').getAttribute('aria-busy') === 'false'",
        timeout=20000,
    )


def body_text(page, selector: str) -> str:
    return page.eval_on_selector(
        selector, "el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim()"
    )


def page_text(page) -> str:
    return page.evaluate("() => document.body.innerText.replace(/\\s+/g, ' ').trim()")


def api_calls(tracker: Tracker) -> list[dict]:
    return [item for item in tracker.responses if "/api/" in item["url"]]


def scenario_401(browser, *, cid: str, cookie: str | None, expected: str, viewport):
    context, page, tracker = new_page(browser, viewport=viewport)
    if cookie:
        add_cookie(context, BASE, cookie)
    goto_shell(page, BASE + "/?from=qa&x=1")
    try:
        page.wait_for_function("() => location.pathname === '/pilot/login'", timeout=20000)
    except PlaywrightError:
        pass
    final_url = page.url
    parsed = urllib.parse.urlparse(final_url)
    next_values = urllib.parse.parse_qs(parsed.query).get("next", [])
    next_value = next_values[0] if next_values else None

    headers = {"Cookie": f"fishagent_pilot={cookie}"} if cookie else {}
    direct = requests.get(
        BASE + "/api/fish-activity?lat=30.657&lon=104.066", headers=headers, timeout=15
    )
    try:
        code = direct.json()["detail"]["code"]
    except Exception:
        code = ""

    login_page_ok = page.evaluate(
        "() => !!document.getElementById('login-form') && document.title.includes('登录')"
    )
    time.sleep(1.0)
    stable_url = page.url
    redirects = [url for url in tracker.navigations if "/pilot/login" in url]

    check(
        cid + "-redirect",
        parsed.path == "/pilot/login" and next_value == "/?from=qa&x=1" and login_page_ok,
        {"url": final_url, "next": next_value, "loginPage": login_page_ok},
    )
    check(cid + "-code", direct.status_code == 401 and code == expected, {"status": direct.status_code, "code": code})
    check(
        cid + "-no-loop",
        stable_url == final_url and len(redirects) == 1,
        {"before": final_url, "after": stable_url, "loginNavigations": len(redirects)},
    )
    if expected == "UNAUTHORIZED":
        page.screenshot(path=str(OUT / "cr03c-c01-401-login-375.png"), full_page=False)
    context.close()
    return {"url": final_url, "next": next_value, "code": code}


def scenario_login_ui(browser):
    context, page, tracker = new_page(browser, viewport={"width": 1280, "height": 900})
    goto_shell(page, BASE + "/?from=qa&x=1")
    page.wait_for_function("() => location.pathname === '/pilot/login'", timeout=20000)
    page.fill("#code", INVITE)
    page.click("#submit")
    try:
        page.wait_for_function(
            "() => location.pathname === '/' && location.search.includes('from=qa')",
            timeout=20000,
        )
    except PlaywrightError:
        pass
    wait_spots(page)
    page.wait_for_timeout(500)

    statuses = api_calls(tracker)
    ok_statuses = [item["status"] for item in statuses]
    landed = page.url.startswith(BASE + "/?from=qa")
    cards = page.eval_on_selector_all(
        "#spots-body .spot h3", "els => els.map(el => el.textContent.trim())"
    )
    text = page_text(page)
    check(
        "C02-login-next-roundtrip",
        landed and len(cards) >= 1 and ok_statuses.count(200) >= 2,
        {"url": page.url, "cards": len(cards), "apiStatuses": ok_statuses},
    )
    check(
        "C02-compliance",
        FORBIDDEN in text and "AI 生成" in text and "免责声明" in text,
        {"forbidden": FORBIDDEN in text, "ai": "AI 生成" in text, "disclaimer": "免责声明" in text},
    )
    page.screenshot(path=str(OUT / "cr03c-c02-normal-1280.png"), full_page=False)
    context.close()
    return tracker


def scenario_no_loop_under_pilot(browser):
    context, page, tracker = new_page(browser, viewport={"width": 375, "height": 812})
    add_cookie(context, BASE, login_api())
    goto_shell(page, BASE + "/")
    wait_spots(page)
    page.evaluate("() => history.replaceState({}, '', '/pilot/probe')")
    add_cookie(context, BASE, "v1.bad.bad")
    page.select_option("#radius-select", "100")
    page.wait_for_timeout(1600)
    path = urllib.parse.urlparse(page.url).path
    error_text = (body_text(page, "#activity-body") + " " + body_text(page, "#spots-body")).strip()
    statuses = [item["status"] for item in api_calls(tracker)]
    check(
        "C03-pilot-path-no-redirect",
        path == "/pilot/probe" and 401 in statuses and ("登录" in error_text or "凭证" in error_text),
        {"path": path, "apiStatuses": statuses, "error": error_text[:160]},
    )
    context.close()


def scenario_non_contract_401(browser):
    context, page, tracker = new_page(browser, viewport={"width": 375, "height": 812}, block_sw=True)
    add_cookie(context, BASE, login_api())
    goto_shell(page, BASE + "/")
    wait_spots(page)
    context.route(
        "**/api/fish-activity*",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body=json.dumps({"detail": {"code": "INVALID_INVITE_CODE", "message": "邀请码无效"}}),
        ),
    )
    page.select_option("#radius-select", "100")
    page.wait_for_timeout(1600)
    path = urllib.parse.urlparse(page.url).path
    text = body_text(page, "#activity-body")
    check(
        "C04-non-contract-401-no-redirect",
        path == "/" and "/pilot/login" not in page.url and "邀请码无效" in text,
        {"path": path, "activity": text[:160]},
    )
    context.close()


def scenario_429(browser, *, base: str, cid: str, expect_phrase: str, screenshot: str):
    context, page, tracker = new_page(browser, viewport={"width": 375, "height": 812}, block_sw=True)
    add_cookie(context, base, login_api(base))
    goto_shell(page, base + "/")
    page.wait_for_timeout(2600)

    rate = [item for item in api_calls(tracker) if item["status"] == 429]
    retry_after = [item["headers"].get("retry-after") for item in rate if item["headers"].get("retry-after")]
    text = page_text(page)
    first_429 = rate[0]["t"] if rate else None
    after = [
        item
        for item in tracker.requests
        if "/api/" in item["url"] and first_429 and item["t"] > first_429 + 0.5
    ]
    check(
        cid + "-429-response",
        bool(rate) and bool(retry_after) and retry_after[0].isdigit() and int(retry_after[0]) > 0,
        {"count": len(rate), "retryAfter": retry_after[:2], "statuses": [r["status"] for r in api_calls(tracker)]},
    )
    check(
        cid + "-message",
        expect_phrase in text and "秒后重试" in text,
        {"expect": expect_phrase, "text": text[:240]},
    )
    check(
        cid + "-no-auto-retry",
        len(after) == 0,
        {"requestsAfter429": [item["url"] for item in after][:3], "windowSeconds": 2.1},
    )
    page.screenshot(path=str(OUT / screenshot), full_page=False)
    context.close()


def scenario_mobile_normal(browser, *, ua: str, cid: str, scheme: str):
    context, page, tracker = new_page(browser, viewport={"width": 375, "height": 812}, ua=ua)
    goto_shell(page, BASE + "/?mock=1")
    wait_spots(page, 5)
    page.wait_for_timeout(400)
    cards = page.evaluate(
        """() => Array.from(document.querySelectorAll('#spots-body .spot')).map(li => ({
          name: li.querySelector('h3') ? li.querySelector('h3').textContent.trim() : '',
          appHref: li.querySelector('.spot-nav a.btn-ghost') ? li.querySelector('.spot-nav a.btn-ghost').getAttribute('href') : null,
          fallbackHref: li.querySelector('.spot-nav a.nav-fallback') ? li.querySelector('.spot-nav a.nav-fallback').getAttribute('href') : null,
          fallbackTarget: li.querySelector('.spot-nav a.nav-fallback') ? li.querySelector('.spot-nav a.nav-fallback').getAttribute('target') : null,
          fallbackRel: li.querySelector('.spot-nav a.nav-fallback') ? li.querySelector('.spot-nav a.nav-fallback').getAttribute('rel') : null
        }))"""
    )
    app_ok = all(card["appHref"] and card["appHref"].startswith(scheme) for card in cards)
    fallback_ok = all(
        card["fallbackHref"]
        and card["fallbackHref"].startswith("https://uri.amap.com/marker?")
        and card["fallbackTarget"] == "_blank"
        and "noopener" in (card["fallbackRel"] or "")
        for card in cards
    )
    metrics = page.evaluate(
        "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, iw: innerWidth})"
    )
    text = page_text(page)
    check(
        cid,
        len(cards) == 5 and app_ok and fallback_ok and FORBIDDEN in text and "免责声明" in text,
        {"cards": len(cards), "appOk": app_ok, "fallbackOk": fallback_ok, "overflow": metrics},
    )
    check(
        cid + "-console",
        not tracker.console and not tracker.pageerrors,
        {"console": tracker.console[:2], "pageerror": tracker.pageerrors[:2]},
    )
    context.close()


def scenario_batch_and_console(browser, tracker: Tracker, page):
    names1 = page.eval_on_selector_all(
        "#spots-body .spot h3", "els => els.map(el => el.textContent.trim())"
    )
    spots_before = len([item for item in tracker.requests if "/api/spots/recommend" in item["url"]])
    page.click("#spots-refresh")
    page.wait_for_function(
        "() => document.querySelectorAll('#spots-body .spot').length === 1", timeout=10000
    )
    names2 = page.eval_on_selector_all(
        "#spots-body .spot h3", "els => els.map(el => el.textContent.trim())"
    )
    status1 = page.eval_on_selector("#status-region", "el => el.textContent.trim()")
    page.click("#spots-refresh")
    page.wait_for_function(
        "() => document.querySelectorAll('#spots-body .spot').length === 5", timeout=10000
    )
    names3 = page.eval_on_selector_all(
        "#spots-body .spot h3", "els => els.map(el => el.textContent.trim())"
    )
    status2 = page.eval_on_selector("#status-region", "el => el.textContent.trim()")
    spots_after = len([item for item in tracker.requests if "/api/spots/recommend" in item["url"]])
    metrics = page.evaluate(
        "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, iw: innerWidth})"
    )
    check(
        "C02-cr01-batch",
        names1 != names2 and names1 == names3 and spots_after == spots_before
        and "已换到下一批钓位。" in status1
        and "已展示全部推荐，已回到第 1 批。" in status2,
        {"first": names1, "second": names2, "third": names3, "status1": status1, "status2": status2, "spotsRequests": [spots_before, spots_after]},
    )
    check(
        "C02-desktop-console-overflow",
        not tracker.console and not tracker.pageerrors and metrics["sw"] == metrics["cw"] == metrics["iw"],
        {"console": tracker.console[:2], "pageerror": tracker.pageerrors[:2], "metrics": metrics},
    )


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME, headless=True)

        scenario_401(browser, cid="C01A-unauthorized", cookie=None, expected="UNAUTHORIZED", viewport={"width": 375, "height": 812})
        scenario_401(browser, cid="C01B-invalid-token", cookie="v1.bad.bad", expected="INVALID_TOKEN", viewport={"width": 375, "height": 812})
        scenario_401(
            browser,
            cid="C01C-expired-token",
            cookie=forged_token(-120),
            expected="TOKEN_EXPIRED",
            viewport={"width": 375, "height": 812},
        )

        tracker = scenario_login_ui(browser)
        # CR-01 batch/console regression uses the client-side mock (10 spots) so
        # the 5-per-batch pagination path is exercised deterministically.
        context, page, tracker2 = new_page(browser, viewport={"width": 1280, "height": 900})
        goto_shell(page, BASE + "/?mock=1")
        wait_spots(page, 5)
        scenario_batch_and_console(browser, tracker2, page)
        context.close()

        scenario_no_loop_under_pilot(browser)
        scenario_non_contract_401(browser)

        scenario_429(
            browser,
            base=RATE,
            cid="C05-rate-limited",
            expect_phrase="请求过于频繁",
            screenshot="cr03c-c05-rate-limit-375.png",
        )
        scenario_429(
            browser,
            base=QUOTA,
            cid="C06-quota-exceeded",
            expect_phrase="今日额度已用完",
            screenshot="cr03c-c06-quota-375.png",
        )

        scenario_mobile_normal(browser, ua=UA_IPHONE, cid="C07-iphone-cr02", scheme="iosamap://path?")
        scenario_mobile_normal(browser, ua=UA_ANDROID, cid="C08-android-cr02", scheme="amapuri://route/plan/?")

        browser.close()

    guard = (OUT / "upstream-guard-8099-c.log")
    guard_text = guard.read_text(encoding="utf-8") if guard.exists() else ""
    check("C09-no-upstream-connections", "CONNECT" not in guard_text, guard_text.strip()[:200])

    total = len(results)
    passed = sum(1 for item in results if item["ok"])
    summary = {
        "base_normal": BASE,
        "base_rate": RATE,
        "base_quota": QUOTA,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "failures": [item for item in results if not item["ok"]],
        "results": results,
    }
    (OUT / "cr03-c-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"TOTAL {passed}/{total} passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
