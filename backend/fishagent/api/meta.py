"""Health and demo metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from fishagent import __version__
from fishagent.config import get_settings
from fishagent.schemas import DemoConfigResponse, HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", version=__version__, mock_mode=settings.mock_mode)


@router.get("/api/demo/config", response_model=DemoConfigResponse)
async def demo_config() -> DemoConfigResponse:
    settings = get_settings()
    return DemoConfigResponse(
        mock_mode=settings.mock_mode,
        default_location={"lat": 30.2741, "lon": 120.1551, "name": "杭州西湖"},
        scenarios=["excellent", "good", "fair", "poor", "no_go"],
        ai_disclosure="本内容由 AI 生成，仅供参考，不承诺渔获。",
        disclaimer="本工具仅供钓鱼参考，不承诺渔获；请遵守当地禁钓规定，注意涉水安全。",
        timezone="Asia/Shanghai",
    )
