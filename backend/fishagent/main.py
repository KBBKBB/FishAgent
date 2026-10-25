"""FastAPI application factory and static H5 hosting."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from fishagent import __version__
from fishagent.api.fish_activity import router as fish_router
from fishagent.api.meta import router as meta_router
from fishagent.api.spots import router as spots_router
from fishagent.config import get_settings
from fishagent.errors import ApiError, register_exception_handlers
from fishagent.pilot import get_pilot_state
from fishagent.pilot.middleware import PilotAccessMiddleware, quota_exceeded_handler
from fishagent.pilot.router import router as pilot_router
from fishagent.providers.base import UpstreamQuotaExceeded

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


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
    app.include_router(_agent_router())
    if pilot_state is not None:
        app.include_router(pilot_router)

    @app.get("/api/{path:path}", include_in_schema=False)
    async def unknown_api_route(path: str) -> None:
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
