"""Health and demo metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from fishagent import __version__
from fishagent.config import get_settings
from fishagent.schemas import DemoConfigResponse, HealthResponse

router = APIRouter(tags=["meta"])


def _speech_ready(settings) -> bool:
    """Whether the page should offer a mic button.

    Deliberately stricter than "a provider is configured": a vosk provider
    with no model on disk would accept the press and then fail every time, so
    the button would exist only to produce an error. Checking the model
    directory costs a couple of stat calls and runs once per health poll.
    """
    provider = (settings.speech_provider or "").strip().lower()
    if provider in ("", "none"):
        return False
    if provider == "vosk":
        from fishagent.providers.speech_vosk import model_available

        return model_available(settings.speech_model_path)
    # An unknown provider name is a configuration mistake. Report it as
    # unavailable rather than promising a feature that will 501.
    return False


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, response: Response) -> HealthResponse:
    settings = get_settings()
    holder = getattr(request.app.state, "build_id", None)
    # no-store because this is the endpoint the page polls to find out whether
    # it is stale; a cached answer would make it poll forever and never see the
    # change. Responses are tiny and this is a LAN address.
    response.headers["Cache-Control"] = "no-store"
    return HealthResponse(
        status="ok",
        version=__version__,
        build=holder.get() if holder is not None else "",
        mock_mode=settings.mock_mode,
        speech_enabled=_speech_ready(settings),
    )


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
