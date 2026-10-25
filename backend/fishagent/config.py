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
