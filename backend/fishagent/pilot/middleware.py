"""Pilot auth, CORS-adjacent hardening, rate limiting and quota pre-checks."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from fishagent.errors import AUTH_CHALLENGE
from fishagent.pilot.state import PilotState
from fishagent.pilot.tokens import TokenError, token_fingerprint
from fishagent.providers.base import UpstreamQuotaExceeded

logger = logging.getLogger(__name__)

LOGIN_API_PATH = "/api/pilot/login"
SESSION_API_PATH = "/api/pilot/session"
LOGOUT_API_PATH = "/api/pilot/logout"
AGENT_CHAT_PATH = "/api/agent/chat"
PUBLIC_API_PATHS = frozenset(
    {LOGIN_API_PATH, SESSION_API_PATH, LOGOUT_API_PATH, "/api/demo/config"}
)
_LLM_CALLS_PER_CHAT = 2


def requires_auth(path: str) -> bool:
    if path in PUBLIC_API_PATHS:
        return False
    if path.startswith("/api/"):
        return True
    return (
        path == "/docs"
        or path.startswith("/docs/")
        or path == "/redoc"
        or path.startswith("/redoc/")
        or path == "/openapi.json"
    )


def extract_token(request: Request, cookie_name: str) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        candidate = header[7:].strip()
        if candidate:
            return candidate
    return request.cookies.get(cookie_name)


def client_ip(request: Request, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        for header in ("cf-connecting-ip", "x-real-ip"):
            value = request.headers.get(header, "").strip()
            if value:
                return value
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    retry_after: int | None = None,
) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if status_code == 401:
        headers["WWW-Authenticate"] = AUTH_CHALLENGE
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, int(retry_after)))
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message}},
        headers=headers,
    )


def quota_response(exc: UpstreamQuotaExceeded) -> JSONResponse:
    return _error(
        429,
        "QUOTA_EXCEEDED",
        "今日上游配额已用尽，请明日再试",
        retry_after=exc.retry_after_seconds,
    )


async def quota_exceeded_handler(_: Request, exc: UpstreamQuotaExceeded) -> JSONResponse:
    logger.warning("upstream daily quota exhausted provider=%s", exc.provider)
    return quota_response(exc)


class PilotAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, state: PilotState) -> None:
        super().__init__(app)
        self.state = state

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        ip = client_ip(request, self.state.trust_proxy_headers)

        if path == LOGIN_API_PATH:
            retry = self.state.login_limiter.hit(f"login:{ip}")
            if retry is not None:
                return _error(
                    429, "RATE_LIMITED", "尝试过于频繁，请稍后再试", retry_after=retry
                )
            return await call_next(request)

        if request.method == "OPTIONS" or not requires_auth(path):
            return await call_next(request)

        retry = self.state.ip_limiter.hit(f"ip:{ip}")
        if retry is not None:
            return _error(429, "RATE_LIMITED", "请求过于频繁，请稍后再试", retry_after=retry)

        token = extract_token(request, self.state.cookie_name)
        if not token:
            return _error(401, "UNAUTHORIZED", "请先使用邀请码登录")
        try:
            self.state.tokens.verify(token)
        except TokenError as exc:
            message = "登录已过期，请重新登录" if exc.code == "TOKEN_EXPIRED" else "登录凭证无效"
            return _error(401, exc.code, message)

        fingerprint = token_fingerprint(token)
        retry = self.state.token_limiter.hit(f"token:{fingerprint}")
        if retry is not None:
            return _error(429, "RATE_LIMITED", "请求过于频繁，请稍后再试", retry_after=retry)

        try:
            if path == AGENT_CHAT_PATH:
                # The agent graph swallows tool exceptions, so reserve the LLM
                # budget up front and refuse before any upstream call.
                if self.state.llm_quota_enabled:
                    self.state.ledger.consume("llm", _LLM_CALLS_PER_CHAT)
                self.state.ledger.check_available("amap")
                self.state.ledger.check_available("open_meteo")
        except UpstreamQuotaExceeded as exc:
            return quota_response(exc)

        request.state.pilot_ip = ip
        request.state.pilot_token_fp = fingerprint
        # Downstream (the agent's internal tool calls) re-enters the app and is
        # therefore authenticated again. Handing it the caller's token is what
        # keeps that second check honest instead of bypassing it.
        request.state.pilot_token = token
        response = await call_next(request)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
