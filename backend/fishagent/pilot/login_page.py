"""Server-rendered pilot login page (no external assets, no secrets)."""

from __future__ import annotations

LOGIN_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="color-scheme" content="dark">
<title>FishAgent 试点登录</title>
<style>
  :root {
    --ink: #06110f;
    --deep: #0b1f1c;
    --mist: #dcebe4;
    --muted: #8fa8a0;
    --accent: #f2b45c;
    --line: rgba(220, 235, 228, 0.14);
    --danger: #ff9a8a;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    color: var(--mist);
    background:
      radial-gradient(120% 90% at 15% 0%, #16443b 0%, transparent 55%),
      radial-gradient(90% 80% at 90% 100%, #123a44 0%, transparent 60%),
      linear-gradient(160deg, var(--deep), var(--ink) 70%);
    font-family: "Songti SC", "STSong", "Noto Serif SC", "Source Han Serif SC",
      "Iowan Old Style", Georgia, serif;
    display: grid;
    place-items: center;
    padding: 24px;
    min-height: 100dvh;
  }
  body::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    opacity: 0.35;
    background-image: repeating-linear-gradient(
      0deg,
      rgba(255, 255, 255, 0.025) 0 1px,
      transparent 1px 3px
    );
    mix-blend-mode: soft-light;
  }
  main {
    position: relative;
    width: min(420px, 100%);
    padding: 40px 32px 32px;
    border: 1px solid var(--line);
    border-radius: 18px;
    background: linear-gradient(180deg, rgba(11, 31, 28, 0.94), rgba(6, 17, 15, 0.9));
    box-shadow: 0 30px 80px rgba(0, 0, 0, 0.45);
    overflow: hidden;
  }
  main::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    width: 3px;
    height: 100%;
    background: linear-gradient(180deg, var(--accent), transparent 70%);
  }
  .eyebrow {
    margin: 0 0 18px;
    font: 600 12px/1.4 "Gill Sans", "Avenir Next Condensed", "PingFang SC",
      sans-serif;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--accent);
  }
  h1 {
    margin: 0 0 12px;
    font-size: clamp(30px, 7vw, 40px);
    line-height: 1.12;
    font-weight: 600;
    letter-spacing: 0.01em;
  }
  .lede {
    margin: 0 0 28px;
    color: var(--muted);
    font-size: 15px;
    line-height: 1.7;
  }
  label {
    display: block;
    margin-bottom: 8px;
    font: 500 13px/1.4 "Gill Sans", "Avenir Next Condensed", "PingFang SC",
      sans-serif;
    letter-spacing: 0.08em;
    color: var(--mist);
  }
  input {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: rgba(4, 14, 12, 0.7);
    color: var(--mist);
    font: 500 16px/1.4 "Gill Sans", "Avenir Next Condensed", "PingFang SC",
      sans-serif;
    letter-spacing: 0.04em;
    transition: border-color 160ms ease, box-shadow 160ms ease;
  }
  input:focus-visible {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(242, 180, 92, 0.22);
  }
  button {
    width: 100%;
    min-height: 48px;
    margin-top: 16px;
    border: 0;
    border-radius: 10px;
    background: var(--accent);
    color: #1a1206;
    font: 700 15px/1 "Gill Sans", "Avenir Next Condensed", "PingFang SC",
      sans-serif;
    letter-spacing: 0.12em;
    cursor: pointer;
    transition: transform 160ms ease, filter 160ms ease;
  }
  button:hover { filter: brightness(1.06); }
  button:active { transform: translateY(1px); }
  button:disabled { opacity: 0.55; cursor: progress; }
  #status {
    min-height: 22px;
    margin: 14px 0 0;
    font: 500 13px/1.5 "Gill Sans", "Avenir Next Condensed", "PingFang SC",
      sans-serif;
    color: var(--danger);
  }
  #status[data-tone="ok"] { color: var(--accent); }
  .foot {
    margin: 26px 0 0;
    padding-top: 18px;
    border-top: 1px solid var(--line);
    color: var(--muted);
    font-size: 12px;
    line-height: 1.6;
  }
  @media (max-width: 420px) {
    main { padding: 32px 22px 26px; border-radius: 14px; }
  }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
</style>
</head>
<body>
<main>
  <p class="eyebrow">FishAgent Pilot</p>
  <h1>凭邀请码进入</h1>
  <p class="lede">当前为小范围试用。输入管理员提供的邀请码后，本机将获得一枚短期访问凭证。</p>
  <form id="login-form" novalidate>
    <label for="code">邀请码</label>
    <input id="code" name="code" type="password" autocomplete="one-time-code"
      spellcheck="false" autocapitalize="off" required autofocus maxlength="128">
    <button type="submit" id="submit">进入</button>
    <p id="status" role="status" aria-live="polite"></p>
  </form>
  <p class="foot">凭证仅保存在浏览器的 HttpOnly Cookie 中，不会写入页面或日志。请勿转发邀请码。</p>
</main>
<script>
  (() => {
    const form = document.getElementById("login-form");
    const input = document.getElementById("code");
    const status = document.getElementById("status");
    const button = document.getElementById("submit");

    const next = (() => {
      const raw = new URLSearchParams(window.location.search).get("next");
      if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/";
      return raw;
    })();

    const setStatus = (text, tone) => {
      status.textContent = text;
      if (tone) status.dataset.tone = tone;
      else delete status.dataset.tone;
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const code = input.value.trim();
      if (!code) {
        setStatus("请输入邀请码");
        input.focus();
        return;
      }
      button.disabled = true;
      setStatus("正在验证…");
      try {
        const response = await fetch("/api/pilot/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ code }),
        });
        if (response.ok) {
          setStatus("验证通过，正在进入…", "ok");
          window.location.replace(next);
          return;
        }
        if (response.status === 429) {
          setStatus("尝试过于频繁，请稍后再试。");
        } else if (response.status === 422) {
          setStatus("邀请码格式不正确。");
        } else {
          setStatus("邀请码不正确，请核对后重试。");
        }
      } catch (error) {
        setStatus("网络异常，请稍后重试。");
      } finally {
        button.disabled = false;
      }
    });
  })();
</script>
</body>
</html>
"""

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def render_login_page() -> str:
    return LOGIN_PAGE_HTML
