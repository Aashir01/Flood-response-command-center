"""One error model for every Brain route (contract 8c): ``{"error": {code, message, details?}}``.

Messages never contain secrets, prompts, stack traces or file paths."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stitch_common.brain_api import ApiError, ApiErrorBody, ApiErrorCode

STATUS: dict[str, int] = {
    "INVALID_INPUT": 400,
    "NOT_FOUND": 404,
    "RATE_LIMITED": 429,
    "BUSY": 429,
    "CANCELLED": 409,
    "PAYLOAD_TOO_LARGE": 413,
    "UPSTREAM_UNAVAILABLE": 503,
    "INTERNAL": 500,
}


class ApiException(Exception):
    def __init__(
        self,
        code: ApiErrorCode,
        message: str,
        *,
        status: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ApiErrorCode = code
        self.message = message
        self.status = status or STATUS[code]
        self.details = details
        self.headers = headers


def error_body(code: ApiErrorCode, message: str, details: dict[str, Any] | None = None) -> Any:
    return ApiError(error=ApiErrorBody(code=code, message=message, details=details)).model_dump(
        mode="json", exclude_none=True
    )


def error_response(
    code: ApiErrorCode,
    message: str,
    *,
    status: int | None = None,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        error_body(code, message, details), status_code=status or STATUS[code], headers=headers
    )


_HTTP_CODES: dict[int, ApiErrorCode] = {
    400: "INVALID_INPUT",
    404: "NOT_FOUND",
    405: "INVALID_INPUT",
    413: "PAYLOAD_TOO_LARGE",
    422: "INVALID_INPUT",
    429: "RATE_LIMITED",
    503: "UPSTREAM_UNAVAILABLE",
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(_req: Request, exc: ApiException) -> JSONResponse:
        return error_response(
            exc.code, exc.message, status=exc.status, details=exc.details, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", ""))[:200]}
            for e in exc.errors()[:10]
        ]
        return error_response(
            "INVALID_INPUT", "request validation failed", status=422, details={"errors": errors}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "INTERNAL")
        msg = exc.detail if isinstance(exc.detail, str) else "error"
        return error_response(code, msg, status=exc.status_code)

    @app.exception_handler(Exception)
    async def _internal(_req: Request, _exc: Exception) -> JSONResponse:
        return error_response("INTERNAL", "internal error")


__all__ = ["ApiException", "error_body", "error_response", "install"]
