"""M2 HTTP API —— 标准库实现（零依赖），预留 FastAPI 迁移位。

路由：
  GET /health
  GET /api/v1/fish-activity?lat=&lng=
  GET /api/v1/spots?lat=&lng=&limit=

说明：本项目 M1 原型即「零依赖 Python」；M2 初期沿用标准库便于内测与复现，
待依赖可安装（CI 环境）后，Handler 逻辑可直接迁移到 FastAPI 路由。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, services


def _floats(q: dict, *names: str) -> list[float]:
    out: list[float] = []
    for n in names:
        if n not in q or not q[n]:
            raise ValueError(f"缺少参数 {n}")
        try:
            out.append(float(q[n][0]))
        except ValueError as exc:
            raise ValueError(f"参数 {n} 必须为数字") from exc
    return out


class Handler(BaseHTTPRequestHandler):
    ctx: services.ServiceContext | None = None
    server_version = "FishAgentM2/" + __version__

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 保持静默，交由结构化日志
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 标准库约定
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/health":
                return self._send(200, {"status": "ok", "version": __version__,
                                        "offline": bool(getattr(self.ctx, "offline", False))})
            if u.path == "/api/v1/fish-activity":
                lat, lng = _floats(q, "lat", "lng")
                return self._send(200, services.analyze_fish_activity(self.ctx, lat, lng))
            if u.path == "/api/v1/spots":
                lat, lng = _floats(q, "lat", "lng")
                limit = int(q.get("limit", ["5"])[0])
                return self._send(200, services.recommend_spots(self.ctx, lat, lng, limit=limit))
            return self._send(404, {"error": "not_found", "path": u.path})
        except ValueError as exc:
            return self._send(400, {"error": "bad_request", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 兜底为 500，避免泄露堆栈
            return self._send(500, {"error": "internal", "detail": str(exc)})


def make_server(host: str = "127.0.0.1", port: int = 8000, ctx=None) -> ThreadingHTTPServer:
    Handler.ctx = ctx or services.build_context(offline=True)
    return ThreadingHTTPServer((host, port), Handler)
