"""Unified error bodies: every 4xx/5xx answers {"detail": {code, message, fields?}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

AUTH_CHALLENGE = 'Bearer realm="fishagent-pilot"'

_STATUS_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields


def error_headers(status_code: int) -> dict[str, str]:
    """Headers that every error response with this status must carry."""
    if status_code != 401:
        return {}
    return {"Cache-Control": "no-store", "WWW-Authenticate": AUTH_CHALLENGE}


def _detail_body(
    code: str,
    message: str,
    fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return {"detail": detail}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_detail_body(exc.code, exc.message, exc.fields),
            headers=error_headers(exc.status_code),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: list[dict[str, str]] = []
        for error in exc.errors():
            location = [
                str(part)
                for part in error.get("loc", ())
                if part not in ("query", "body", "path")
            ]
            fields.append(
                {
                    "field": ".".join(location) or "request",
                    "message": str(error.get("msg", "参数不合法")),
                }
            )
        return JSONResponse(
            status_code=422,
            content=_detail_body("VALIDATION_ERROR", "参数校验失败", fields or None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and exc.detail.get("code"):
            detail = {
                "code": str(exc.detail["code"]),
                "message": str(exc.detail.get("message") or exc.detail["code"]),
            }
            if exc.detail.get("fields"):
                detail["fields"] = exc.detail["fields"]
        else:
            code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
            detail = {"code": code, "message": str(exc.detail or code)}
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled server error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_detail_body("INTERNAL_ERROR", "服务器内部错误"),
        )
