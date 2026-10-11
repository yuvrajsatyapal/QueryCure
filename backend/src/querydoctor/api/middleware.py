import hmac

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from querydoctor.api.deps import CSRF_COOKIE
from querydoctor.core.errors import CsrfFailedError, PayloadTooLargeError, QueryDoctorError
from querydoctor.core.ids import new_request_id
from querydoctor.core.logging import get_logger

MAX_REQUEST_BYTES = 6 * 1024 * 1024  # 5 MB plan uploads plus envelope overhead
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Creating a session is the one mutation without a CSRF token yet (ADR-0013); login CSRF on an
# anonymous/local session grants nothing.
CSRF_EXEMPT = frozenset({("POST", "/api/v1/session")})

log = get_logger("querydoctor.api")


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _envelope(err: QueryDoctorError, request: Request) -> JSONResponse:
    return JSONResponse(err.to_envelope(request_id=_request_id(request)), status_code=err.status)


class MaxBodySizeMiddleware:
    """Refuse oversized bodies before they are buffered, with or without Content-Length.

    Declared sizes are refused up front. Streamed bodies raise PayloadTooLargeError from
    `receive`, which surfaces in the endpoint and is rendered by the normal envelope handler.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            err = PayloadTooLargeError(f"Request body is larger than {self.max_bytes} bytes.")
            response = JSONResponse(err.to_envelope(request_id=new_request_id()), status_code=413)
            await response(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise PayloadTooLargeError(
                        f"Request body is larger than {self.max_bytes} bytes."
                    )
            return message

        await self.app(scope, limited_receive, send)


class RequestIdMiddleware:
    """Plain ASGI (not BaseHTTPMiddleware) so exceptions are never wrapped in task groups."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


class CsrfMiddleware:
    """Double-submit token: the `qd_csrf` cookie must equal the X-CSRF-Token header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        method, path = request.method, request.url.path
        if method not in SAFE_METHODS and (method, path) not in CSRF_EXEMPT:
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get("X-CSRF-Token", "")
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                response = _envelope(CsrfFailedError("Missing or invalid CSRF token."), request)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


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
