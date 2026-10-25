"""CR-03 A: independent PWA shell checks against an isolated mock instance.

Read-only QA harness. No product code changes, no real provider calls.
Target: http://127.0.0.1:8033 (uvicorn, FISHAGENT_MOCK_MODE=true,
FISHAGENT_PUBLIC_ACCESS_ENABLED=false).
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8033"
OUT = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
UA_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)
UA_IPADOS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)

FORBIDDEN_TEXT = (
    "禁钓提示：国家公园、自然保护区、饮用水水源保护区等保护地禁止垂钓；"
    "其他水域是否可钓以当地公告为准。"
)
OFFLINE_API_MESSAGE = "当前处于离线状态，无法获取实时数据；请恢复网络后重试。"
STANDALONE_INIT = """
(() => {
  const orig = window.matchMedia.bind(window);
  window.matchMedia = (q) => {
    if (/\\(display-mode:\\s*standalone\\)/.test(String(q))) {
      return {matches:true, media:String(q), onchange:null,
              addEventListener(){}, removeEventListener(){},
              addListener(){}, removeListener(){}, dispatchEvent(){return false;}};
    }
    return orig(q);
  };
  Object.defineProperty(navigator, 'standalone', {get: () => true});
})();
"""
PRECACHE = [
    "/",
    "/index.html",
    "/styles.css",
    "/app.js",
    "/manifest.webmanifest",
    "/icons/icon-192.png",
    "/icons/icon-512.png",
    "/icons/icon-maskable-192.png",
    "/icons/icon-maskable-512.png",
    "/icons/apple-touch-icon-180.png",
]

results: list[dict] = []
console_events: dict[str, list] = {}


def check(cid: str, ok: bool, detail=None) -> None:
    results.append({"id": cid, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), cid, "" if detail is None else str(detail)[:400])


def http_get(path: str) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "cr03-qa"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, dict(resp.headers), resp.read()


def icons_check() -> None:
    expected = {
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-maskable-192.png": (192, 192),
        "icon-maskable-512.png": (512, 512),
        "apple-touch-icon-180.png": (180, 180),
    }
    ok_all = True
    details = {}
    for name, size in expected.items():
        status, headers, body = http_get("/icons/" + name)
        w, h = struct.unpack(">II", body[16:24])
        good = status == 200 and headers.get("content-type") == "image/png" and (w, h) == size
        ok_all = ok_all and good
        details[name] = {"status": status, "type": headers.get("content-type"), "size": [w, h], "bytes": len(body)}
    check("A01-icons-real-dimensions", ok_all, details)


def manifest_check() -> None:
    status, headers, body = http_get("/manifest.webmanifest")
    mime = headers.get("content-type", "")
    data = json.loads(body.decode("utf-8"))
    check("A02-manifest-mime", status == 200 and mime.split(";")[0].strip() == "application/manifest+json", mime)
    fields = {
        "id": "/",
        "name": "FishAgent · 鱼情与钓位助手",
        "short_name": "FishAgent",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "lang": "zh-CN",
        "dir": "ltr",
        "theme_color": "#0e6b52",
        "background_color": "#f3f0e7",
        "prefer_related_applications": False,
    }
    bad = {k: data.get(k) for k, v in fields.items() if data.get(k) != v}
    check("A03-manifest-fields", not bad, bad or "all match")
    icons = data.get("icons") or []
    sizes = [(i.get("sizes"), i.get("purpose"), i.get("type")) for i in icons]
    expected = [
        ("192x192", "any", "image/png"),
        ("512x512", "any", "image/png"),
        ("192x192", "maskable", "image/png"),
        ("512x512", "maskable", "image/png"),
    ]
    check("A04-manifest-icons", len(icons) == 4 and sizes == expected, sizes)
    check(
        "A05-manifest-display-override",
        data.get("display_override") == ["standalone", "minimal-ui"],
        data.get("display_override"),
    )


def index_check() -> None:
    status, headers, body = http_get("/index.html")
    html = body.decode("utf-8")
    mime = headers.get("content-type", "")
    check("A06-index-served", status == 200 and mime.startswith("text/html"), mime)
    meta_expect = {
        'name="theme-color" content="#0e6b52"': True,
        'name="apple-mobile-web-app-capable" content="yes"': True,
        'name="apple-mobile-web-app-status-bar-style" content="default"': True,
        'name="apple-mobile-web-app-title" content="FishAgent"': True,
        'name="mobile-web-app-capable" content="yes"': True,
    }
    missing = [m for m in meta_expect if m not in html]
    check("A07-ios-meta", not missing, missing or "all present")
    links = {
        'rel="apple-touch-icon" sizes="180x180" href="./icons/apple-touch-icon-180.png"': "apple-touch-icon",
        'rel="manifest" href="./manifest.webmanifest"': "manifest",
        'rel="icon" type="image/png" sizes="192x192" href="./icons/icon-192.png"': "icon192",
    }
    missing_links = [v for k, v in links.items() if k not in html]
    check("A08-icon-and-manifest-links", not missing_links, missing_links or "all present")
    check("A09-forbidden-notice-exact", FORBIDDEN_TEXT in html, "exact text present" if FORBIDDEN_TEXT in html else "missing")
    check(
        "A10-disclosure-present",
        "AI 生成 · 仅供参考" in html and "不承诺渔获" in html and "免责声明" in html,
        "ai badge + disclaimer present",
    )


def sw_static_check() -> None:
    status, headers, body = http_get("/sw.js")
    text = body.decode("utf-8")
    ok = (
        status == 200
        and headers.get("content-type", "").startswith("application/javascript")
        and "CACHE_VERSION = 'fishagent-v1'" in text
        and "url.pathname.indexOf('/api/') === 0" in text
        and "offlineApiResponse" in text
        and "clients.claim()" in text
    )
    check("A11-sw-source", ok, {"status": status, "type": headers.get("content-type"), "bytes": len(body)})


def new_context(browser, *, viewport, ua=None, mobile=False, touch=False):
    kwargs = {"viewport": viewport, "device_scale_factor": 2 if mobile else 1}
    if ua:
        kwargs["user_agent"] = ua
    if mobile:
        kwargs["is_mobile"] = True
    if touch:
        kwargs["has_touch"] = True
    return browser.new_context(**kwargs)


def attach_collectors(page, label: str) -> None:
    events = {"console_error": [], "pageerror": [], "requests": []}
    console_events[label] = events
    page.on("console", lambda msg: events["console_error"].append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: events["pageerror"].append(str(exc)))
    page.on("request", lambda req: events["requests"].append(req.url))


def wait_for_spots(page, timeout=20000):
    page.wait_for_function(
        "() => { const b=document.getElementById('spots-body'); "
        "return b && b.getAttribute('aria-busy')==='false'; }",
        timeout=timeout,
    )


def overflow(page) -> dict:
    return page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth,"
        " clientWidth: document.documentElement.clientWidth,"
        " bodyScrollWidth: document.body.scrollWidth, innerWidth: window.innerWidth})"
    )


def installability_check(p) -> None:
    """Chrome reports 'in-incognito' for Playwright's default contexts, so use a
    persistent (non-incognito) profile for the real installability verdict."""
    profile = tempfile.mkdtemp(prefix="cr03-profile-")
    ctx = p.chromium.launch_persistent_context(
        profile,
        executable_path=CHROME,
        headless=True,
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    wait_for_spots(page)
    page.wait_for_function(
        "() => navigator.serviceWorker && navigator.serviceWorker.controller", timeout=20000
    )
    cdp = ctx.new_cdp_session(page)
    cdp.send("Page.enable")
    manifest = cdp.send("Page.getAppManifest")
    installability = cdp.send("Page.getInstallabilityErrors")
    errors = manifest.get("errors") or []
    inst_errors = installability.get("installabilityErrors") or []
    check(
        "A15-chrome-installability",
        not errors and not inst_errors,
        {"manifestUrl": manifest.get("url"), "manifestErrors": errors, "installabilityErrors": inst_errors},
    )
    page.screenshot(path=str(OUT / "cr03-pwa-persistent-1280.png"), full_page=False)
    ctx.close()


def standalone_checks(browser) -> None:
    """Simulated standalone display-mode (real standalone launch is device-only).

    CDP Emulation.setEmulatedMedia(display-mode) does not change matchMedia in
    this Chrome build, so the app's display-mode contract is simulated via
    matchMedia/navigator.standalone overrides.
    """
    ctx = new_context(browser, viewport={"width": 1280, "height": 900})
    ctx.add_init_script(STANDALONE_INIT)
    page = ctx.new_page()
    page.goto(BASE + "/?mock=1", wait_until="load")
    wait_for_spots(page)
    page.evaluate("() => window.dispatchEvent(new Event('beforeinstallprompt', {cancelable:true}))")
    state = page.evaluate(
        "() => ({mq: matchMedia('(display-mode: standalone)').matches,"
        " standalone: navigator.standalone,"
        " installHidden: document.getElementById('install-btn').hidden,"
        " hintHidden: document.getElementById('ios-install-hint').hidden})"
    )
    check(
        "A17-standalone-hides-install",
        state["mq"] and state["installHidden"] and state["hintHidden"],
        state,
    )
    ctx.close()

    ios_ctx = new_context(
        browser, viewport={"width": 375, "height": 812}, ua=UA_IPHONE, mobile=True, touch=True
    )
    ios_ctx.add_init_script(STANDALONE_INIT)
    ios_page = ios_ctx.new_page()
    ios_page.goto(BASE + "/?mock=1", wait_until="load")
    wait_for_spots(ios_page)
    ios_state = ios_page.evaluate(
        "() => ({mq: matchMedia('(display-mode: standalone)').matches,"
        " standalone: navigator.standalone,"
        " hintHidden: document.getElementById('ios-install-hint').hidden,"
        " installHidden: document.getElementById('install-btn').hidden})"
    )
    check(
        "A30-ios-standalone-hides-guidance",
        ios_state["mq"] and ios_state["standalone"] and ios_state["hintHidden"] and ios_state["installHidden"],
        ios_state,
    )
    ios_ctx.close()


def desktop_checks(browser) -> None:
    ctx = new_context(browser, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    attach_collectors(page, "desktop")
    page.goto(BASE + "/", wait_until="load")
    wait_for_spots(page)

    # service worker registration / takeover
    sw = page.evaluate(
        """async () => {
          if (!('serviceWorker' in navigator)) return {supported:false};
          const reg = await navigator.serviceWorker.ready;
          for (let i=0;i<40 && !navigator.serviceWorker.controller;i++) {
            await new Promise(r=>setTimeout(r,100));
          }
          return {
            supported: true,
            secure: window.isSecureContext,
            scope: reg.scope,
            active: reg.active && reg.active.scriptURL,
            controller: navigator.serviceWorker.controller && navigator.serviceWorker.controller.scriptURL,
            state: reg.active && reg.active.state
          };
        }"""
    )
    check(
        "A12-sw-registration-takeover",
        sw.get("supported") and sw.get("secure") and sw.get("active", "").endswith("/sw.js")
        and sw.get("controller", "").endswith("/sw.js"),
        sw,
    )

    # precache contents
    cache = page.evaluate(
        """async () => {
          const names = await caches.keys();
          const out = {names, entries: [], apiEntries: []};
          for (const n of names) {
            const c = await caches.open(n);
            const keys = await c.keys();
            out.entries.push([n, keys.map(r => new URL(r.url).pathname)]);
            out.apiEntries.push(...keys.map(r => new URL(r.url).pathname).filter(p => p.startsWith('/api/')));
          }
          return out;
        }"""
    )
    static_names = [n for n in cache["names"] if n == "fishagent-v1-static"]
    cached_paths = []
    for name, paths in cache["entries"]:
        if name == "fishagent-v1-static":
            cached_paths = paths
    missing = [p for p in PRECACHE if p not in cached_paths]
    check("A13-shell-precache", bool(static_names) and not missing, {"names": cache["names"], "missing": missing, "count": len(cached_paths)})
    check("A14-api-not-cached", not cache["apiEntries"], cache["apiEntries"] or "no /api entries")

    # Chrome installability is verified in a non-incognito persistent profile (installability_check).

    # install button default vs synthetic beforeinstallprompt
    btn_hidden_default = page.evaluate("() => document.getElementById('install-btn').hidden")
    page.evaluate("() => window.dispatchEvent(new Event('beforeinstallprompt', {cancelable:true}))")
    btn_shown_after = page.evaluate("() => document.getElementById('install-btn').hidden")
    check("A16-android-install-entry", btn_hidden_default is True and btn_shown_after is False, {"defaultHidden": btn_hidden_default, "afterPromptHidden": btn_shown_after})

    # caching after live traffic: /api must still be absent, shell present
    page.reload(wait_until="load")
    wait_for_spots(page)
    cache_after = page.evaluate(
        """async () => {
          const names = await caches.keys();
          let api = [];
          for (const n of names) {
            const c = await caches.open(n);
            api.push(...(await c.keys()).map(r => new URL(r.url).pathname).filter(p => p.startsWith('/api/')));
          }
          return {names, api};
        }"""
    )
    check("A18-api-never-cached-after-traffic", not cache_after["api"], cache_after)

    ov = overflow(page)
    check("A19-desktop-1280-no-overflow", ov["scrollWidth"] <= ov["innerWidth"] and ov["bodyScrollWidth"] <= ov["innerWidth"], ov)
    page.screenshot(path=str(OUT / "cr03-pwa-desktop-1280.png"), full_page=False)

    # offline: SW returns honest 503 for API, no fake data
    pre_offline_errors = list(console_events["desktop"]["console_error"])
    pre_offline_pageerrors = list(console_events["desktop"]["pageerror"])
    ctx.set_offline(True)
    offline_api = page.evaluate(
        """async () => {
          try {
            const r = await fetch('/api/spots/recommend?lat=30.2741&lon=120.1551&radius_km=50&limit=10');
            let body = null; try { body = await r.json(); } catch (e) {}
            return {status: r.status, body};
          } catch (e) { return {error: String(e)}; }
        }"""
    )
    body = offline_api.get("body") or {}
    detail = body.get("detail") if isinstance(body, dict) else None
    check(
        "A20-offline-api-503-honest",
        offline_api.get("status") == 503 and detail == OFFLINE_API_MESSAGE and "spots" not in (body or {}),
        offline_api,
    )

    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    offline_ui = page.evaluate(
        """() => ({
          online: navigator.onLine,
          bannerHidden: document.getElementById('offline-banner').hidden,
          bannerText: document.getElementById('offline-banner').textContent.trim(),
          spotCards: document.querySelectorAll('#spots-body .spot').length,
          spotText: document.getElementById('spots-body').textContent.trim().slice(0,160),
          activityText: document.getElementById('activity-body').textContent.trim().slice(0,160),
          controlled: !!navigator.serviceWorker.controller,
          hasMockSpotNames: /青山水库|镜湖湿地野塘|苕溪河湾|白鹭湖|九龙湖|锦江|府河/.test(document.body.innerText)
        })"""
    )
    check(
        "A21-offline-shell-no-fake-data",
        offline_ui["controlled"] and offline_ui["spotCards"] == 0
        and offline_ui["hasMockSpotNames"] is False
        and ("离线" in offline_ui["spotText"] or "离线" in offline_ui["activityText"]),
        offline_ui,
    )
    page.screenshot(path=str(OUT / "cr03-pwa-offline-1280.png"), full_page=False)

    # recovery (CDP offline emulation does not always flip navigator.onLine,
    # so the online transition is dispatched explicitly to exercise the handler)
    ctx.set_offline(False)
    page.evaluate("() => window.dispatchEvent(new Event('online'))")
    page.wait_for_timeout(2500)
    recovered = page.evaluate(
        """() => ({
          online: navigator.onLine,
          bannerHidden: document.getElementById('offline-banner').hidden,
          spotCards: document.querySelectorAll('#spots-body .spot').length,
          status: document.getElementById('status-region').textContent.trim()
        })"""
    )
    check("A22-network-recovery", recovered["online"] and recovered["bannerHidden"] and recovered["spotCards"] >= 1, recovered)

    # version cleanup: legacy cache must be removed on activate
    page.evaluate("async () => { const c = await caches.open('fishagent-v0-legacy'); await c.put('/legacy-test', new Response('x')); }")
    page.evaluate("async () => { const r = await navigator.serviceWorker.getRegistration(); if (r) await r.unregister(); }")
    page.reload(wait_until="load")
    page.evaluate(
        """async () => {
          const reg = await navigator.serviceWorker.ready;
          for (let i=0;i<50 && !navigator.serviceWorker.controller;i++) await new Promise(r=>setTimeout(r,100));
          return reg.active && reg.active.state;
        }"""
    )
    page.wait_for_timeout(800)
    cleanup = page.evaluate(
        """async () => {
          const names = await caches.keys();
          let legacy = false;
          for (const n of names) { const c = await caches.open(n); legacy = legacy || !!(await c.match('/legacy-test')); }
          return {names, legacyPresent: legacy, controller: !!navigator.serviceWorker.controller};
        }"""
    )
    check(
        "A23-version-cleanup",
        cleanup["legacyPresent"] is False and cleanup["names"] == ["fishagent-v1-static"] and cleanup["controller"],
        cleanup,
    )

    # truthful offline signal: with navigator.onLine=false the banner must show
    ctx.add_init_script("Object.defineProperty(navigator, 'onLine', {get: () => false})")
    ctx.set_offline(True)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    banner = page.evaluate(
        """() => ({
          online: navigator.onLine,
          hidden: document.getElementById('offline-banner').hidden,
          text: document.getElementById('offline-banner').textContent.trim(),
          spotCards: document.querySelectorAll('#spots-body .spot').length
        })"""
    )
    check(
        "A21b-offline-banner-truthful",
        banner["online"] is False and banner["hidden"] is False
        and "离线" in banner["text"] and banner["spotCards"] == 0,
        banner,
    )
    ctx.set_offline(False)

    check(
        "A24-desktop-console-clean",
        not pre_offline_errors and not pre_offline_pageerrors,
        {"console": pre_offline_errors, "pageerror": pre_offline_pageerrors},
    )
    offline_errors = [
        e for e in console_events["desktop"]["console_error"] if e not in pre_offline_errors
    ]
    check(
        "A24b-offline-console-expected-503",
        bool(offline_errors) and all("503" in e for e in offline_errors),
        offline_errors,
    )
    ctx.close()


def mobile_common(browser, *, label, ua, viewport, touch=True):
    ctx = new_context(browser, viewport=viewport, ua=ua, mobile=True, touch=touch)
    page = ctx.new_page()
    attach_collectors(page, label)
    page.goto(BASE + "/?mock=1", wait_until="load")
    wait_for_spots(page)
    cards = page.evaluate(
        """() => Array.from(document.querySelectorAll('#spots-body .spot')).map(li => ({
          name: li.querySelector('h3') ? li.querySelector('h3').textContent : '',
          appHref: li.querySelector('.spot-nav a.btn-ghost') ? li.querySelector('.spot-nav a.btn-ghost').getAttribute('href') : null,
          fallbackHref: li.querySelector('.spot-nav a.nav-fallback') ? li.querySelector('.spot-nav a.nav-fallback').getAttribute('href') : null,
          fallbackTarget: li.querySelector('.spot-nav a.nav-fallback') ? li.querySelector('.spot-nav a.nav-fallback').getAttribute('target') : null,
          fallbackRel: li.querySelector('.spot-nav a.nav-fallback') ? li.querySelector('.spot-nav a.nav-fallback').getAttribute('rel') : null
        }))"""
    )
    return ctx, page, cards


def iphone_checks(browser) -> None:
    ctx, page, cards = mobile_common(browser, label="iphone", ua=UA_IPHONE, viewport={"width": 375, "height": 812})
    hint = page.evaluate(
        """() => ({hidden: document.getElementById('ios-install-hint').hidden,
                  text: document.getElementById('ios-install-hint').textContent.replace(/\\s+/g,' ').trim(),
                  installHidden: document.getElementById('install-btn').hidden})"""
    )
    check("A25-iphone-ios-guidance", hint["hidden"] is False and "分享" in hint["text"] and "添加到主屏幕" in hint["text"], hint)
    check("A26-iphone-cards-five", len(cards) == 5 and all(c["name"] for c in cards), [c["name"] for c in cards])
    app_ok = all(c["appHref"] and c["appHref"].startswith("iosamap://path?") for c in cards)
    fallback_ok = all(
        c["fallbackHref"] and c["fallbackHref"].startswith("https://uri.amap.com/marker?")
        and c["fallbackTarget"] == "_blank" and "noopener" in (c["fallbackRel"] or "")
        for c in cards
    )
    check("A27-iphone-amap-app-scheme", app_ok, [c["appHref"] for c in cards])
    check("A28-iphone-fallback-web", fallback_ok, [c["fallbackHref"] for c in cards])

    # dismiss persistence
    page.click("#ios-install-close")
    after_close = page.evaluate("() => ({hidden: document.getElementById('ios-install-hint').hidden, flag: sessionStorage.getItem('fishagent.iosInstallHintDismissed')})")
    page.reload(wait_until="load")
    wait_for_spots(page)
    after_reload = page.evaluate("() => document.getElementById('ios-install-hint').hidden")
    check("A29-ios-guidance-dismiss-persist", after_close["hidden"] and after_close["flag"] == "1" and after_reload is True, {"afterClose": after_close, "afterReloadHidden": after_reload})

    # standalone display-mode is covered by standalone_checks() in a fresh context
    ov = overflow(page)
    check("A31-iphone-375-no-overflow", ov["scrollWidth"] <= 375 and ov["bodyScrollWidth"] <= 375, ov)
    page.screenshot(path=str(OUT / "cr03-pwa-iphone-375.png"), full_page=False)

    # CR-01 batch switching with client mock (6 spots -> 5 + 1 + rollover)
    page.goto(BASE + "/?mock=1", wait_until="load")
    wait_for_spots(page)
    first = page.evaluate("() => Array.from(document.querySelectorAll('#spots-body .spot h3')).map(n => n.textContent)")
    req_before = len([u for u in console_events["iphone"]["requests"] if "/api/spots/recommend" in u])
    t0 = time.time()
    page.click("#spots-refresh")
    page.wait_for_timeout(150)
    second = page.evaluate("() => Array.from(document.querySelectorAll('#spots-body .spot h3')).map(n => n.textContent)")
    status1 = page.evaluate("() => document.getElementById('status-region').textContent.trim()")
    click_ms = round((time.time() - t0) * 1000, 1)
    req_after = len([u for u in console_events["iphone"]["requests"] if "/api/spots/recommend" in u])
    page.click("#spots-refresh")
    page.wait_for_timeout(150)
    third = page.evaluate("() => Array.from(document.querySelectorAll('#spots-body .spot h3')).map(n => n.textContent)")
    status2 = page.evaluate("() => document.getElementById('status-region').textContent.trim()")
    check(
        "A32-cr01-batch-switch-no-request",
        len(first) == 5 and len(second) == 1 and len(third) == 5
        and first == third and req_after == req_before == 0
        and status1 == "已换到下一批钓位。" and status2 == "已展示全部推荐，已回到第 1 批。",
        {"first": first, "second": second, "third": third, "status1": status1, "status2": status2, "clickMs": click_ms, "requests": req_after},
    )

    events = console_events["iphone"]
    check("A33-iphone-console-clean", not events["console_error"] and not events["pageerror"], {"console": events["console_error"], "pageerror": events["pageerror"]})
    ctx.close()


def android_checks(browser) -> None:
    ctx, page, cards = mobile_common(browser, label="android", ua=UA_ANDROID, viewport={"width": 375, "height": 812})
    app_ok = all(c["appHref"] and c["appHref"].startswith("amapuri://route/plan/?") for c in cards)
    fallback_ok = all(c["fallbackHref"] and c["fallbackHref"].startswith("https://") for c in cards)
    check("A34-android-amap-app-scheme", len(cards) == 5 and app_ok and fallback_ok, [c["appHref"] for c in cards])
    hint_hidden = page.evaluate("() => document.getElementById('ios-install-hint').hidden")
    check("A35-android-no-ios-guidance", hint_hidden is True, hint_hidden)
    page.evaluate("() => window.dispatchEvent(new Event('beforeinstallprompt', {cancelable:true}))")
    btn = page.evaluate("() => document.getElementById('install-btn').hidden")
    check("A36-android-install-entry-visible", btn is False, btn)
    ov = overflow(page)
    check("A37-android-375-no-overflow", ov["scrollWidth"] <= 375 and ov["bodyScrollWidth"] <= 375, ov)
    page.screenshot(path=str(OUT / "cr03-pwa-android-375.png"), full_page=False)
    events = console_events["android"]
    check("A38-android-console-clean", not events["console_error"] and not events["pageerror"], {"console": events["console_error"], "pageerror": events["pageerror"]})
    ctx.close()


def ipados_checks(browser) -> None:
    ctx = new_context(browser, viewport={"width": 768, "height": 1024}, ua=UA_IPADOS, mobile=True, touch=True)
    ctx.add_init_script("Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5})")
    page = ctx.new_page()
    attach_collectors(page, "ipados")
    page.goto(BASE + "/?mock=1", wait_until="load")
    wait_for_spots(page)
    cards = page.evaluate(
        """() => Array.from(document.querySelectorAll('#spots-body .spot')).map(li => ({
          name: li.querySelector('h3') ? li.querySelector('h3').textContent : '',
          appHref: li.querySelector('.spot-nav a.btn-ghost') ? li.querySelector('.spot-nav a.btn-ghost').getAttribute('href') : null
        }))"""
    )
    hint = page.evaluate("() => ({hidden: document.getElementById('ios-install-hint').hidden, touch: navigator.maxTouchPoints})")
    check(
        "A39-ipados-macintosh-touch",
        len(cards) == 5 and all(c["appHref"] and c["appHref"].startswith("iosamap://path?") for c in cards) and hint["touch"] > 1,
        {"cards": [c["appHref"] for c in cards], "hint": hint},
    )
    ov = overflow(page)
    check("A40-ipados-768-no-overflow", ov["scrollWidth"] <= 768 and ov["bodyScrollWidth"] <= 768, ov)
    page.screenshot(path=str(OUT / "cr03-pwa-ipados-768.png"), full_page=False)
    events = console_events["ipados"]
    check("A41-ipados-console-clean", not events["console_error"] and not events["pageerror"], {"console": events["console_error"], "pageerror": events["pageerror"]})
    ctx.close()


def cr01_live_request_checks(browser) -> None:
    ctx = new_context(browser, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    attach_collectors(page, "cr01-live")
    page.goto(BASE + "/", wait_until="load")
    wait_for_spots(page)
    spot_reqs = [u for u in console_events["cr01-live"]["requests"] if "/api/spots/recommend" in u]
    check("A42-cr01-one-spots-request-limit10", len(spot_reqs) == 1 and "limit=10" in spot_reqs[0] and "offset=" not in spot_reqs[0], spot_reqs)
    cards = page.evaluate("() => Array.from(document.querySelectorAll('#spots-body .spot h3')).map(n => n.textContent)")
    check("A43-cr01-first-render-local-slice", 1 <= len(cards) <= 5, cards)
    # radius change triggers a fresh request with radius_km=100
    page.select_option("#radius-select", "100")
    page.wait_for_timeout(1800)
    spot_reqs2 = [u for u in console_events["cr01-live"]["requests"] if "/api/spots/recommend" in u]
    check(
        "A44-cr01-radius-refetch",
        len(spot_reqs2) == 2 and "radius_km=100" in spot_reqs2[-1] and "limit=10" in spot_reqs2[-1],
        spot_reqs2,
    )
    events = console_events["cr01-live"]
    check("A45-cr01-live-console-clean", not events["console_error"] and not events["pageerror"], {"console": events["console_error"], "pageerror": events["pageerror"]})
    ctx.close()


def main() -> int:
    icons_check()
    manifest_check()
    index_check()
    sw_static_check()
    with sync_playwright() as p:
        installability_check(p)
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        desktop_checks(browser)
        standalone_checks(browser)
        iphone_checks(browser)
        android_checks(browser)
        ipados_checks(browser)
        cr01_live_request_checks(browser)
        browser.close()

    passed = sum(1 for r in results if r["ok"])
    summary = {
        "base_url": BASE,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "failures": [r for r in results if not r["ok"]],
        "results": results,
    }
    (OUT / "cr03-pwa-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTOTAL {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
