"""合规红线检查：前端无密钥/无第三方直连、AI 标识与免责、禁止承诺性表述。

依据：docs/api-contract.md v1.1 §2/§3/§6，docs/mvp-prd.md §6.5（AT-UI-02/05/06、AT-CMP-01~03）。
"""

from __future__ import annotations

import re

import pytest
from conftest import BEIJING, HANGZHOU, PROMISE_PATTERNS, REPO_ROOT

WEB_DIR = REPO_ROOT / "web"
BACKEND_DIR = REPO_ROOT / "backend"

SECRET_PATTERNS = (
    "AMAP_WEB_KEY",
    "LLM_API_KEY",
    "OPEN_METEO_KEY",
    "sk-",
)

DIRECT_ENDPOINTS = (
    "restapi.amap.com",
    "api.open-meteo.com",
    "api.openai.com",
)


def _web_texts() -> list[tuple[str, str]]:
    files = [p for p in WEB_DIR.glob("*") if p.suffix in {".html", ".js", ".css"}]
    assert files, "web/ 下未找到可检查的前端文件"
    return [(p.name, p.read_text(encoding="utf-8", errors="ignore")) for p in files]


def test_web_sources_contain_no_key_or_direct_provider_calls():
    findings: list[str] = []
    for name, text in _web_texts():
        for pattern in SECRET_PATTERNS:
            if pattern in text:
                findings.append(f"{name} 含敏感串 {pattern!r}")
        for endpoint in DIRECT_ENDPOINTS:
            if endpoint in text:
                findings.append(f"{name} 直连第三方 {endpoint}")
    assert not findings, "前端合规违规：\n" + "\n".join(findings)


def test_web_only_calls_same_origin_api():
    offenders: list[str] = []
    for name, text in _web_texts():
        if name.endswith(".js"):
            for url in re.findall(r"https?://[^\s'\"`)]+", text):
                if "/api/" in url and "localhost" not in url and "127.0.0.1" not in url:
                    offenders.append(f"{name}: {url}")
    assert not offenders, "前端存在跨域 API 调用：\n" + "\n".join(offenders)


def test_env_example_has_placeholders_only():
    env_example = BACKEND_DIR / ".env.example"
    if not env_example.exists():
        pytest.fail(f"缺少 {env_example}：契约 §3 要求提供仅含占位符的 .env.example")
    text = env_example.read_text(encoding="utf-8")
    assert "AMAP_WEB_KEY" in text, ".env.example 未声明 AMAP_WEB_KEY"
    assert "LLM_API_KEY" in text, ".env.example 未声明 LLM_API_KEY"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip().strip("\"'")
        if key.strip() in {"AMAP_WEB_KEY", "LLM_API_KEY"}:
            normalized = value.lower().replace("_", "-")
            assert not value or normalized.startswith("your-") or value.startswith("<"), (
                f".env.example 中 {key.strip()} 不是占位符"
            )
        assert not value.startswith("sk-"), f".env.example 泄露疑似真实 Key：{key.strip()}"


def test_homepage_has_required_disclosures(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    for required in ("AI 生成", "免责声明", "不承诺渔获", "Mock 模式"):
        assert required in html, f"首页缺少合规文案：{required}"
    assert "禁钓" in html, "首页缺少遵守禁钓规定的提示"


def test_homepage_has_no_promise_or_raw_weather_panel(client):
    html = client.get("/").text
    for pattern in PROMISE_PATTERNS:
        assert pattern not in html, f"首页含承诺性表述：{pattern}"


@pytest.mark.parametrize("scenario", ["excellent", "good", "fair", "poor", "no_go"])
def test_fish_activity_response_compliance(client, scenario):
    response = client.get(
        "/api/fish-activity",
        params={"lat": HANGZHOU["lat"], "lon": HANGZHOU["lon"], "scenario": scenario},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_disclosure"] == "本结论由 AI 辅助生成，仅供参考，不承诺渔获。"
    assert any("Mock" in source for source in payload["data_sources"]), (
        "data_sources 缺少 Mock 标识"
    )
    serialized = response.text
    for pattern in PROMISE_PATTERNS:
        assert pattern not in serialized, f"鱼情响应含承诺性表述：{pattern}"


def test_chat_response_compliance(client):
    response = client.post(
        "/api/agent/chat",
        json={
            "message": "今天这气压适合钓鱼吗？",
            "location": {"lat": BEIJING["lat"], "lon": BEIJING["lon"], "name": "北京"},
            "session_id": "compliance-session",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_disclosure"] == "本内容由 AI 生成，仅供参考，不承诺渔获。"
    assert payload["mode"] == "fallback"
    serialized = response.text
    for pattern in PROMISE_PATTERNS:
        assert pattern not in serialized, f"对话响应含承诺性表述：{pattern}"


# --- 定位失败必须说真话 -----------------------------------------------------
#
# 实故障（2026-10-29，真机）：用 http 访问局域网 IP 时 isSecureContext=false，
# 浏览器把「根本不提供定位」也报成 PERMISSION_DENIED（code 1），前端于是统一
# 提示「定位权限被拒绝」。用户去找一个永远改不好的权限开关，而真正的原因是
# 地址不是 https。这与把服务超时说成「不支持的图片格式」是同一类错误。


def test_geolocation_checks_secure_context_before_blaming_permission():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function handleGeolocation()")
    end = app_js.index("function hidePlaceLists", start)
    body = app_js[start:end]

    # 必须先分辨非安全上下文，再进入 getCurrentPosition。
    secure_at = body.find("isSecureContext")
    call_at = body.find("getCurrentPosition")
    assert secure_at != -1, "定位逻辑未检查 isSecureContext，http 下必然谎报权限被拒"
    assert call_at != -1
    assert secure_at < call_at, "isSecureContext 检查必须在调用定位之前"


def test_geolocation_rejection_message_is_not_the_only_code_1_explanation():
    """code 1 有两种原因，提示里不能只说「权限被拒绝」这一种。"""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function handleGeolocation()")
    end = app_js.index("function hidePlaceLists", start)
    body = app_js[start:end]
    assert "不是权限问题" in body, "非安全上下文的提示需明确排除权限原因"


def test_geolocation_hides_stale_picker_results():
    """点了定位却仍显示上次搜索的列表，会让人以为定位没生效。"""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function handleGeolocation()")
    end = app_js.index("function hidePlaceLists", start)
    body = app_js[start:end]
    assert "hidePlaceLists()" in body


#
# 版本提示（2026-10-30）：用户要在界面上知道有新版本，并在自己想的时候升级。
#
# 两条约束来自这个页面自己的性质，不是偏好：
#   1. 不能自动刷新——表单、已选鱼获照片、对话都只在内存里（照片明确不落盘），
#      静默 reload 会把这些直接吞掉。
#   2. 关闭后再弹就只是噪音：按 build 记住「稍后再说」。


def test_update_is_offered_not_forced():
    """发现新版本只能提示，刷新必须由用户点。"""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function showUpdateBanner")
    end = app_js.index("function checkForUpdate", start)
    body = app_js[start:end]
    assert "reload" not in body, "提示逻辑不得直接刷新页面"
    # How the banner is revealed is an implementation detail; that it is revealed
    # when the server build differs is not.
    assert "setUpdateBannerVisible(true)" in body


def test_update_banner_is_visible_wherever_the_reader_has_scrolled():
    """提示条必须贴在视口上，不能放在文档流顶部。

    部署发生在任意时刻，手机上用户通常早已滚到 Step 3 或对话区。放在文档
    顶部的提示条会被截在视口上方一两千像素处——元素"显示了"，但没人看得见。
    """
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setUpdateBannerVisible" in app_js, (
        "banner 的显隐要收在一处，否则固定定位需要的 body 留白会漏掉"
    )

    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
    start = css.index(".update-banner {")
    body = css[start : css.index("}", start)]
    assert "position: fixed" in body, "提示条必须脱离文档流固定在视口上"

    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert "has-update-banner" not in index_html, "留白类应由脚本按显隐切换添加"


def test_update_dismissal_is_per_build():
    """「稍后再说」要按 build 记住，否则下一轮轮询又把提示弹回来。"""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "updateDismissedBuild === serverBuild" in app_js


def test_update_watch_ignores_uninjected_pages():
    """占位符没被替换时不能当成 build id，否则每次轮询都报「有新版本」。"""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "__FISHAGENT_BUILD__" in app_js
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'name="fishagent-build"' in index_html



# --- 语音输入（CR-06）------------------------------------------------------
#
# 两条约束来自功能本身的性质：
#   1. 识别结果只填进输入框。识别会错，自动发送等于把一次听错变成一条用户
#      从没问过的问题——和"更新提示不自动刷新"是同一条原则。
#   2. 能力判断不能靠 webkitSpeechRecognition 是否存在。实测该构造器在非安全
#      上下文下同样存在，而 navigator.mediaDevices 才真正消失；据构造器显示
#      按钮，用户会得到一个点了没反应的按钮。


def test_voice_result_is_inserted_not_sent():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function sendVoiceForTranscription")
    end = app_js.index("function toggleVoiceCapture", start)
    body = app_js[start:end]
    assert "sendMessage(" not in body, "语音识别结果不得自动发送"
    assert "input.value = text" in body, "识别结果应填入输入框"


def test_voice_capability_check_does_not_trust_the_constructor():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function voiceSupported")
    end = app_js.index("function updateVoiceButton", start)
    body = app_js[start:end]
    assert "isSecureContext" in body, "必须先判安全上下文"
    assert "mediaDevices" in body, "必须以 mediaDevices 为准"
    assert "webkitSpeechRecognition" not in body, (
        "该构造器在非安全上下文下同样存在，不能用作能力判断"
    )


def test_voice_insecure_message_is_not_a_permission_message():
    """同 2026-10-29 定位那次的错误：把协议问题说成权限被拒。"""
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    start = app_js.index("function startVoiceCapture")
    end = app_js.index("function finishVoiceCapture", start)
    body = app_js[start:end]
    assert "不是权限问题" in body
