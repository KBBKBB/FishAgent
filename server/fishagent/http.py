"""极简 HTTP 客户端 —— 仅用标准库, 保证原型零依赖即可运行。

真实服务端实现可替换为 httpx/aiohttp; 这里只服务于 M1 验证。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_UA = "FishAgent-M1-Prototype/0.1 (+https://example.com; research)"


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.body = body
        self.url = url


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: float = 8.0,
    user_agent: str = DEFAULT_UA,
) -> Any:
    """GET 并解析 JSON。params 会做 URL 编码。"""
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 4xx/5xx
        raise HttpError(exc.code, exc.read().decode("utf-8", "ignore"), url) from exc
    except urllib.error.URLError as exc:  # 网络/超时
        raise HttpError(0, str(exc.reason), url) from exc
    return json.loads(raw)
