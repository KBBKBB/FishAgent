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
