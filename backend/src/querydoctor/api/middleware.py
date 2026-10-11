import hmac
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from querydoctor.api.deps import CSRF_COOKIE
from querydoctor.core.errors import CsrfFailedError, QueryDoctorError
from querydoctor.core.ids import new_request_id
from querydoctor.core.logging import get_logger

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Creating a session is the one mutation without a CSRF token yet (ADR-0013); login CSRF on an
# anonymous/local session grants nothing.
CSRF_EXEMPT = frozenset({("POST", "/api/v1/session")})

log = get_logger("querydoctor.api")
Handler = Callable[[Request], Awaitable[Response]]


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _envelope(err: QueryDoctorError, request: Request) -> JSONResponse:
    return JSONResponse(err.to_envelope(request_id=_request_id(request)), status_code=err.status)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request_id = new_request_id()
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        return response


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit token: the `qd_csrf` cookie must equal the X-CSRF-Token header."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        if (
            request.method not in SAFE_METHODS
            and (request.method, request.url.path) not in CSRF_EXEMPT
        ):
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get("X-CSRF-Token", "")
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                return _envelope(CsrfFailedError("Missing or invalid CSRF token."), request)
        return await call_next(request)


def _plain_error(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    """Same envelope as QueryDoctorError, for framework-raised errors (404, validation, crashes)."""
    body = {
        "error": {
            "code": code,
            "message": message,
            "status": status,
            "details": details or [],
            "request_id": _request_id(request),
        }
    }
    return JSONResponse(body, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(QueryDoctorError)
    async def domain_error(request: Request, exc: QueryDoctorError) -> JSONResponse:
        return _envelope(exc, request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        message = "Not found." if exc.status_code == 404 else str(exc.detail)
        code = codes.get(exc.status_code, f"HTTP_{exc.status_code}")
        return _plain_error(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return _plain_error(request, 422, "VALIDATION_ERROR", "Request validation failed.", details)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", exc_info=exc, path=request.url.path)
        return _plain_error(request, 500, "INTERNAL_ERROR", "Internal error.")
