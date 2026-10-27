"""Environment-backed settings. Mock mode is the default and needs no keys."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _normalize_no_proxy() -> None:
    # httpx 0.28.1 parses NO_PROXY entries as URLs and rejects bracketed IPv6 ("[::1]").
    for name in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(name)
        if value and "[" in value:
            os.environ[name] = re.sub(r"\[([^\[\]]+)\]", r"\1", value)


_normalize_no_proxy()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    mock_mode: bool = Field(
        default=True,
        validation_alias=AliasChoices("FISHAGENT_MOCK_MODE", "MOCK_MODE"),
    )
    host: str = Field(default="127.0.0.1", validation_alias="FISHAGENT_HOST")
    port: int = Field(default=8000, validation_alias="FISHAGENT_PORT")

    amap_web_key: str = Field(default="", validation_alias="AMAP_WEB_KEY")
    amap_concurrency: int = Field(
        default=6,
        ge=1,
        le=20,
        validation_alias=AliasChoices("FISHAGENT_AMAP_CONCURRENCY", "AMAP_CONCURRENCY"),
    )
    amap_qps: float = Field(
        default=2.0,
        gt=0,
        le=20,
        validation_alias=AliasChoices("FISHAGENT_AMAP_QPS", "AMAP_QPS"),
    )
    open_meteo_base_url: str = Field(
        default="https://api.open-meteo.com/v1",
        validation_alias="OPEN_METEO_BASE_URL",
    )

    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="gpt-4o-mini", validation_alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=30.0, validation_alias="LLM_TIMEOUT_SECONDS")
    # CR-05 image identification. Empty vision model falls back to LLM_MODEL.
    llm_vision_model: str = Field(default="", validation_alias="LLM_VISION_MODEL")
    identify_max_upload_bytes: int = Field(
        default=8_388_608,
        ge=65_536,
        le=20_971_520,
        validation_alias="FISHAGENT_IDENTIFY_MAX_UPLOAD_BYTES",
    )
    identify_max_side: int = Field(
        default=1280,
        ge=256,
        le=2048,
        validation_alias="FISHAGENT_IDENTIFY_MAX_SIDE",
    )
    # Pixel ceiling. This was the value behind the 2026-10-27 outage: hardcoded
    # at 40 MP it rejected 48 MP iPhone photos. It must stay tunable so a new
    # camera resolution never needs a code change to be accepted.
    identify_max_image_pixels: int = Field(
        default=80_000_000,
        ge=1_000_000,
        le=500_000_000,
        validation_alias="FISHAGENT_IDENTIFY_MAX_IMAGE_PIXELS",
    )
    identify_jpeg_quality: int = Field(
        default=85,
        ge=30,
        le=95,
        validation_alias="FISHAGENT_IDENTIFY_JPEG_QUALITY",
    )
    identify_timeout_seconds: float = Field(
        default=60.0,
        ge=5,
        le=180,
        validation_alias="FISHAGENT_IDENTIFY_TIMEOUT_SECONDS",
    )
    # Decoding a 48 MP photo peaks around 356 MB, so admission is priced by
    # memory (a 12 MP photo costs ~91 MB) rather than by a fixed slot count.
    # This budget is how many decoded photos' worth of RAM we accept at once.
    identify_decode_memory_budget_mb: int = Field(
        default=1536,
        ge=256,
        le=8192,
        validation_alias="FISHAGENT_IDENTIFY_DECODE_MEMORY_BUDGET_MB",
    )
    # Bytes of RAM per decoded pixel, used to price a decode before running it.
    # Measured at ~7.3 on this host; exposed because the true ratio depends on
    # the Pillow/libheif build, so a different deployment may need its own.
    identify_decode_bytes_per_pixel: float = Field(
        default=7.5,
        ge=1.0,
        le=32.0,
        validation_alias="FISHAGENT_IDENTIFY_DECODE_BYTES_PER_PIXEL",
    )
    # A separate cap because decoding is CPU-bound (~1 s for 48 MP on one core);
    # memory headroom alone would let many small photos thrash the CPU.
    identify_max_concurrent_decodes: int = Field(
        default=4,
        ge=1,
        le=8,
        validation_alias="FISHAGENT_IDENTIFY_MAX_CONCURRENT_DECODES",
    )

    # Community species lookup (Step 3 "推荐鱼种"). Empty means "mock" in Mock
    # mode and "none" otherwise, so real deployments never invent community data.
    species_provider: str = Field(
        default="", validation_alias="FISHAGENT_SPECIES_PROVIDER"
    )
    species_timeout_seconds: float = Field(
        default=4.0,
        gt=0,
        le=30,
        validation_alias="FISHAGENT_SPECIES_TIMEOUT_SECONDS",
    )
    species_cache_ttl_seconds: int = Field(
        default=3600,
        ge=0,
        le=86_400,
        validation_alias="FISHAGENT_SPECIES_CACHE_TTL_SECONDS",
    )
    # Phase 2: fetch top result pages and let the LLM extract species. Off by
    # default so Phase 1 behaviour (snippet matching only) stays the baseline.
    species_page_fetch_enabled: bool = Field(
        default=False,
        validation_alias="FISHAGENT_SPECIES_PAGE_FETCH",
    )

    # CR-03 pilot access. Every field below is inert unless
    # FISHAGENT_PUBLIC_ACCESS_ENABLED=true, so the S1 deployment is unchanged.
    public_access_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "FISHAGENT_PUBLIC_ACCESS_ENABLED", "PUBLIC_ACCESS_ENABLED"
        ),
    )
    pilot_invite_code: SecretStr = Field(
        default=SecretStr(""), validation_alias="FISHAGENT_PILOT_INVITE_CODE"
    )
    pilot_token_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="FISHAGENT_PILOT_TOKEN_SECRET"
    )
    pilot_token_ttl_seconds: int = Field(
        default=43_200,
        ge=300,
        le=604_800,
        validation_alias="FISHAGENT_PILOT_TOKEN_TTL_SECONDS",
    )
    pilot_cookie_name: str = Field(
        default="fishagent_pilot", validation_alias="FISHAGENT_PILOT_COOKIE_NAME"
    )
    pilot_cookie_secure: bool = Field(
        default=True, validation_alias="FISHAGENT_PILOT_COOKIE_SECURE"
    )
    pilot_cors_origins: str = Field(
        default="", validation_alias="FISHAGENT_PILOT_CORS_ORIGINS"
    )
    pilot_trust_proxy_headers: bool = Field(
        default=False, validation_alias="FISHAGENT_PILOT_TRUST_PROXY_HEADERS"
    )
    pilot_rate_limit_ip_per_minute: int = Field(
        default=60,
        ge=1,
        le=10_000,
        validation_alias="FISHAGENT_PILOT_RATE_LIMIT_IP_PER_MINUTE",
    )
    pilot_rate_limit_token_per_minute: int = Field(
        default=60,
        ge=1,
        le=10_000,
        validation_alias="FISHAGENT_PILOT_RATE_LIMIT_TOKEN_PER_MINUTE",
    )
    pilot_login_attempts_per_minute: int = Field(
        default=10,
        ge=1,
        le=1_000,
        validation_alias="FISHAGENT_PILOT_LOGIN_ATTEMPTS_PER_MINUTE",
    )
    amap_daily_quota: int = Field(
        default=2_000, ge=0, validation_alias="FISHAGENT_AMAP_DAILY_QUOTA"
    )
    llm_daily_quota: int = Field(
        default=200, ge=0, validation_alias="FISHAGENT_LLM_DAILY_QUOTA"
    )
    open_meteo_daily_quota: int = Field(
        default=1_000, ge=0, validation_alias="FISHAGENT_OPEN_METEO_DAILY_QUOTA"
    )
    quota_day_timezone: str = Field(
        default="Asia/Shanghai", validation_alias="FISHAGENT_QUOTA_DAY_TIMEZONE"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
