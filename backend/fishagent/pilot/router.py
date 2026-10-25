"""Pilot endpoints: login page, invite redemption, session, logout, usage."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from fishagent.errors import ApiError
from fishagent.pilot.login_page import SECURITY_HEADERS, render_login_page
from fishagent.pilot.middleware import LOGIN_API_PATH, extract_token
from fishagent.pilot.state import PilotState
from fishagent.pilot.tokens import TokenError

router = APIRouter(tags=["pilot"])


class LoginPayload(BaseModel):
    code: str = Field(..., min_length=1, max_length=128)


def _state(request: Request) -> PilotState:
    state = getattr(request.app.state, "pilot", None)
    if state is None:  # pragma: no cover - router is mounted only when enabled
        raise ApiError(404, "NOT_FOUND", "接口不存在")
    return state


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/pilot/login", include_in_schema=False)
async def login_page() -> HTMLResponse:
    return HTMLResponse(render_login_page(), headers=SECURITY_HEADERS)


@router.post(LOGIN_API_PATH)
async def login(payload: LoginPayload, request: Request) -> JSONResponse:
    state = _state(request)
    if not state.invite_matches(payload.code):
        raise ApiError(401, "INVALID_INVITE_CODE", "邀请码不正确")
    token, claims = state.tokens.issue()
    response = JSONResponse({"ok": True, "expires_at": _iso(claims.expires_at)})
    response.set_cookie(
        state.cookie_name,
        token,
        max_age=state.token_ttl_seconds,
        httponly=True,
        secure=state.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/api/pilot/logout")
async def logout(request: Request) -> JSONResponse:
    state = _state(request)
    response = JSONResponse({"ok": True})
    response.delete_cookie(state.cookie_name, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/pilot/session")
async def session(request: Request) -> JSONResponse:
    state = _state(request)
    token = extract_token(request, state.cookie_name)
    claims = None
    if token:
        try:
            claims = state.tokens.verify(token)
        except TokenError:
            claims = None
    body: dict[str, object] = {"authenticated": claims is not None}
    if claims is not None:
        body["expires_at"] = _iso(claims.expires_at)
    return JSONResponse(body)


@router.get("/api/pilot/usage")
async def usage(request: Request) -> JSONResponse:
    state = _state(request)
    body = {
        **state.ledger.snapshot(),
        "rate_limits": {
            "ip_per_minute": state.ip_limit_per_minute,
            "token_per_minute": state.token_limit_per_minute,
            "login_per_minute": state.login_limit_per_minute,
        },
        "llm_reserved_per_chat": 2,
    }
    return JSONResponse(body)
