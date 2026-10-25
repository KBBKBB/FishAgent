"""Pilot runtime state derived from environment settings."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fishagent.config import Settings
from fishagent.pilot.limits import DailyQuotaLedger, SlidingWindowLimiter
from fishagent.pilot.tokens import TokenSigner

_MIN_INVITE_CODE_LENGTH = 6


@dataclass
class PilotState:
    invite_code: str
    cookie_name: str
    cookie_secure: bool
    token_ttl_seconds: int
    tokens: TokenSigner
    ledger: DailyQuotaLedger
    ip_limiter: SlidingWindowLimiter
    token_limiter: SlidingWindowLimiter
    login_limiter: SlidingWindowLimiter
    cors_origins: list[str]
    trust_proxy_headers: bool
    llm_quota_enabled: bool
    ip_limit_per_minute: int
    token_limit_per_minute: int
    login_limit_per_minute: int

    def invite_matches(self, candidate: str) -> bool:
        expected = hashlib.sha256(self.invite_code.encode("utf-8")).digest()
        provided = hashlib.sha256((candidate or "").encode("utf-8")).digest()
        return hmac.compare_digest(expected, provided)

    @classmethod
    def from_settings(cls, settings: Settings) -> PilotState:
        invite_code = settings.pilot_invite_code.get_secret_value().strip()
        token_secret = settings.pilot_token_secret.get_secret_value().strip()
        if len(invite_code) < _MIN_INVITE_CODE_LENGTH:
            raise RuntimeError(
                "FISHAGENT_PUBLIC_ACCESS_ENABLED=true requires "
                "FISHAGENT_PILOT_INVITE_CODE with at least 6 characters"
            )
        if len(token_secret) < 32:
            raise RuntimeError(
                "FISHAGENT_PUBLIC_ACCESS_ENABLED=true requires "
                "FISHAGENT_PILOT_TOKEN_SECRET with at least 32 characters"
            )
        try:
            ZoneInfo(settings.quota_day_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise RuntimeError(
                f"invalid FISHAGENT_QUOTA_DAY_TIMEZONE: {settings.quota_day_timezone}"
            ) from exc

        return cls(
            invite_code=invite_code,
            cookie_name=settings.pilot_cookie_name,
            cookie_secure=settings.pilot_cookie_secure,
            token_ttl_seconds=settings.pilot_token_ttl_seconds,
            tokens=TokenSigner(token_secret, settings.pilot_token_ttl_seconds),
            ledger=DailyQuotaLedger(
                {
                    "amap": settings.amap_daily_quota,
                    "open_meteo": settings.open_meteo_daily_quota,
                    "llm": settings.llm_daily_quota,
                },
                day_timezone=settings.quota_day_timezone,
            ),
            ip_limiter=SlidingWindowLimiter(settings.pilot_rate_limit_ip_per_minute),
            token_limiter=SlidingWindowLimiter(settings.pilot_rate_limit_token_per_minute),
            login_limiter=SlidingWindowLimiter(settings.pilot_login_attempts_per_minute),
            cors_origins=_parse_origins(settings.pilot_cors_origins),
            trust_proxy_headers=settings.pilot_trust_proxy_headers,
            llm_quota_enabled=not settings.mock_mode and bool(settings.llm_api_key.strip()),
            ip_limit_per_minute=settings.pilot_rate_limit_ip_per_minute,
            token_limit_per_minute=settings.pilot_rate_limit_token_per_minute,
            login_limit_per_minute=settings.pilot_login_attempts_per_minute,
        )


def _parse_origins(raw: str) -> list[str]:
    origins: list[str] = []
    for entry in raw.split(","):
        value = entry.strip().rstrip("/")
        if not value:
            continue
        if value == "*":
            raise RuntimeError(
                "FISHAGENT_PILOT_CORS_ORIGINS must list explicit origins, not *"
            )
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(f"invalid CORS origin (scheme://host[:port] only): {value}")
        origins.append(f"{parsed.scheme}://{parsed.netloc}")
    return origins
