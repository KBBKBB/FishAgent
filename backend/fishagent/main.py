"""FastAPI application factory and static H5 hosting."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match
from starlette.types import Scope

from fishagent import __version__
from fishagent.api.fish_activity import router as fish_router
from fishagent.api.identify import router as identify_router
from fishagent.api.meta import router as meta_router
from fishagent.api.species import router as species_router
from fishagent.api.spots import router as spots_router
from fishagent.config import get_settings
from fishagent.core.image_guard import sync_pillow_limits
from fishagent.errors import ApiError, register_exception_handlers
from fishagent.pilot import get_pilot_state
from fishagent.pilot.middleware import PilotAccessMiddleware, quota_exceeded_handler
from fishagent.pilot.router import router as pilot_router
from fishagent.providers.base import UpstreamQuotaExceeded

logger = logging.getLogger(__name__)

# Root logging is left at WARNING with no handler, so every ``logger.info`` in
# this package is silently dropped — which is why the 2026-10-27 415 could only
# be diagnosed by reproducing it by hand. Install a handler and let the app's
# own records through; uvicorn's loggers are configured separately and are not
# affected by this. Level is overridable with FISHAGENT_LOG_LEVEL.
_LOG_FORMAT = "%(levelname)s:     [%(name)s] %(message)s"


def _configure_logging() -> None:
    level_name = os.environ.get("FISHAGENT_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=_LOG_FORMAT)
        return
    # Re-configuring on every create_app() call (tests do this) would stack
    # duplicate handlers; only the level needs updating.
    root.setLevel(level)

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

# The unknown-API catch-all must claim every verb. Registered for GET only, any
# unmatched POST falls through to the StaticFiles mount, which answers a bare
# 405 "Method Not Allowed" and hides the real cause (no such route).
_API_CATCH_ALL = "/api/{path:path}"
_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _path_served_by_other_method(app: FastAPI, request: Request) -> bool:
    """True when a real API route matches this path but not this HTTP method.

    ``Match.PARTIAL`` is exactly "the path matches, the verb does not". The
    catch-all itself and the StaticFiles mount always match fully, so they can
    never produce a false positive here.
    """
    scope: Scope = dict(request.scope)
    for route in app.routes:
        # Skip the catch-all itself; it matches every verb by construction.
        if getattr(route, "path", None) == _API_CATCH_ALL:
            continue
        match, _ = route.matches(scope)
        if match == Match.PARTIAL:
            return True
    return False


def _agent_router() -> APIRouter:
    try:
        from fishagent.agent.router import router
    except ModuleNotFoundError:
        logger.exception("agent module unavailable; serving 503 placeholder")

        fallback = APIRouter(prefix="/api/agent", tags=["agent"])

        @fallback.post("/chat")
        async def agent_chat_unavailable() -> None:
            raise ApiError(
                status_code=503,
                code="AGENT_NOT_READY",
                message="Agent 模块尚未就绪",
            )

        return fallback
    return router


def create_app() -> FastAPI:
    _configure_logging()
    # Pillow's bomb threshold is a process global, so it is set once here from
    # settings rather than mutated per upload (concurrent requests would race).
    sync_pillow_limits(get_settings().identify_max_image_pixels)
    app = FastAPI(
        title="FishAgent API",
        version=__version__,
        description="鱼情评分、钓位推荐与自然语言对话（Mock 模式开箱即用）",
    )
    pilot_state = get_pilot_state(get_settings())
    if pilot_state is None:
        # S1 default: no auth, no rate limits, permissive CORS.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        # Added first so CORS stays outermost and preflight never needs a token.
        app.add_middleware(PilotAccessMiddleware, state=pilot_state)
        if pilot_state.cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=pilot_state.cors_origins,
                allow_credentials=True,
                allow_methods=["GET", "HEAD", "POST", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["Retry-After"],
            )
        app.state.pilot = pilot_state
        app.add_exception_handler(UpstreamQuotaExceeded, quota_exceeded_handler)
    register_exception_handlers(app)

    app.include_router(meta_router)
    app.include_router(fish_router)
    app.include_router(spots_router)
    app.include_router(species_router)
    app.include_router(_agent_router())
    app.include_router(identify_router)
    if pilot_state is not None:
        app.include_router(pilot_router)

    # Catch-all for every method, not just GET: a POST to an unregistered API
    # path would otherwise fall through to the StaticFiles mount and answer a
    # bare 405 "Method Not Allowed", which hides the real cause (no such route).
    @app.api_route(_API_CATCH_ALL, methods=_ALL_METHODS, include_in_schema=False)
    async def unknown_api_route(request: Request, path: str) -> None:
        if _path_served_by_other_method(app, request):
            # The route exists under a different verb: 405 is the honest answer.
            raise ApiError(
                status_code=405,
                code="METHOD_NOT_ALLOWED",
                message=f"接口不支持该请求方法：/api/{path}",
            )
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message=f"接口不存在：/api/{path}",
        )

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    else:  # pragma: no cover - defensive for partial checkouts
        logger.warning("web directory not found at %s", WEB_DIR)

    return app


app = create_app()
