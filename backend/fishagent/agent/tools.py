"""Agent tools that consume FishAgent's public API contract in-process."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_INTERNAL_BASE_URL = "http://fishagent.internal"
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
TOOL_TIMEOUT_ENV = "FISHAGENT_TOOL_TIMEOUT_SECONDS"
DEFAULT_TOOL_TIMEOUT_SECONDS = 45.0


class ToolError(RuntimeError):
    """Raised when a tool cannot return a usable result."""


async def get_fish_activity(
    lat: float,
    lon: float,
    *,
    species: str | None = None,
    location_name: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"lat": lat, "lon": lon}
    if species:
        params["species"] = species
    if location_name:
        params["location_name"] = location_name
    return await _request("/api/fish-activity", params, auth_token)


async def recommend_spots(
    lat: float,
    lon: float,
    *,
    species: str | None = None,
    radius_km: float = 100,
    limit: int = 5,
    auth_token: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "limit": limit,
    }
    if species:
        params["species"] = species
    return await _request("/api/spots/recommend", params, auth_token)


async def _request(
    path: str, params: dict[str, Any], auth_token: str | None = None
) -> dict[str, Any]:
    # Imported lazily: main.py mounts agent.router, so a top-level import would cycle.
    from fishagent.main import app

    timeout_seconds = _tool_timeout_seconds()
    transport = httpx.ASGITransport(app=app)
    # The tool re-enters the app through the full middleware stack, so when the
    # pilot gate is on, this request is subject to it like any other. Forwarding
    # the caller's token makes the tool act as that user: the gate's own rules
    # still apply (no bypass path is introduced), and per-token rate limiting
    # and quota accounting see internal calls as the same caller they belong to.
    headers = {"authorization": f"Bearer {auth_token}"} if auth_token else {}
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=_INTERNAL_BASE_URL,
            timeout=timeout_seconds,
        ) as client:
            # ASGITransport does not enforce client timeouts; wait_for is the real guard.
            response = await asyncio.wait_for(
                client.get(path, params=params, headers=headers),
                timeout=timeout_seconds,
            )
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise ToolError("数据服务响应超时，已切换为兜底建议") from exc
    except httpx.HTTPError as exc:
        raise ToolError("数据服务暂时不可用") from exc

    if response.status_code >= 400:
        raise ToolError(_extract_error_message(response))

    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolError("数据服务返回了无法解析的内容") from exc
    if not isinstance(payload, dict):
        raise ToolError("数据服务返回格式不正确")
    return payload


def _tool_timeout_seconds() -> float:
    raw = os.environ.get(TOOL_TIMEOUT_ENV) or _dotenv_timeout()
    if not raw:
        return DEFAULT_TOOL_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid %s, using default", TOOL_TIMEOUT_ENV)
        return DEFAULT_TOOL_TIMEOUT_SECONDS
    if value <= 0:
        logger.warning("non-positive %s, using default", TOOL_TIMEOUT_ENV)
        return DEFAULT_TOOL_TIMEOUT_SECONDS
    return value


def _dotenv_timeout() -> str | None:
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    try:
        value = dotenv_values(_ENV_FILE).get(TOOL_TIMEOUT_ENV)
    except OSError:
        return None
    return str(value) if value else None


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and detail.get("message"):
        return str(detail["message"])
    if isinstance(detail, str):
        return detail
    return f"数据服务返回 HTTP {response.status_code}"
