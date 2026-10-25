"""Stateless pilot access tokens: HMAC-SHA256 over a compact JSON payload.

The token is only ever stored in an HttpOnly cookie or an Authorization header;
it is never returned in a JSON body, logged, or embedded in a page.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

_TOKEN_VERSION = "v1"
_MAX_CLOCK_SKEW_SECONDS = 60
_MIN_SECRET_LENGTH = 32


class TokenError(Exception):
    """Verification failure; `code` is a stable machine-readable reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    issued_at: int
    expires_at: int
    token_id: str


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def token_fingerprint(token: str) -> str:
    """Stable short hash used as a rate-limit key; never reversible to the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class TokenSigner:
    def __init__(
        self,
        secret: str,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(secret) < _MIN_SECRET_LENGTH:
            raise ValueError("pilot token secret must be at least 32 characters")
        if ttl_seconds <= 0:
            raise ValueError("pilot token ttl must be positive")
        self._secret = secret.encode("utf-8")
        self._ttl = ttl_seconds
        self.clock = clock

    def issue(self) -> tuple[str, TokenClaims]:
        now = int(self.clock())
        claims = TokenClaims(
            subject="pilot",
            issued_at=now,
            expires_at=now + self._ttl,
            token_id=secrets.token_hex(8),
        )
        payload = json.dumps(
            {
                "sub": claims.subject,
                "iat": claims.issued_at,
                "exp": claims.expires_at,
                "jti": claims.token_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = _b64encode(payload)
        signature = hmac.new(
            self._secret,
            f"{_TOKEN_VERSION}.{encoded}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{_TOKEN_VERSION}.{encoded}.{_b64encode(signature)}", claims

    def verify(self, token: str) -> TokenClaims:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _TOKEN_VERSION:
            raise TokenError("INVALID_TOKEN")
        try:
            payload_raw = _b64decode(parts[1])
            signature = _b64decode(parts[2])
        except (binascii.Error, ValueError):
            raise TokenError("INVALID_TOKEN") from None

        expected = hmac.new(
            self._secret,
            f"{_TOKEN_VERSION}.{parts[1]}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise TokenError("INVALID_TOKEN")

        try:
            data = json.loads(payload_raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TokenError("INVALID_TOKEN") from None
        if not isinstance(data, dict) or data.get("sub") != "pilot":
            raise TokenError("INVALID_TOKEN")
        try:
            issued_at = int(data["iat"])
            expires_at = int(data["exp"])
            token_id = str(data["jti"])
        except (KeyError, TypeError, ValueError):
            raise TokenError("INVALID_TOKEN") from None

        now = self.clock()
        if expires_at <= now:
            raise TokenError("TOKEN_EXPIRED")
        if issued_at > now + _MAX_CLOCK_SKEW_SECONDS:
            raise TokenError("INVALID_TOKEN")
        return TokenClaims(
            subject="pilot",
            issued_at=issued_at,
            expires_at=expires_at,
            token_id=token_id,
        )
