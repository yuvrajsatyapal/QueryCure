import hmac

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from querycure.api.deps import CSRF_COOKIE
from querycure.api.process_metrics import ProcessMetrics
from querycure.core.errors import CsrfFailedError, PayloadTooLargeError, QueryCureError
from querycure.core.ids import new_request_id
from querycure.core.logging import get_logger

MAX_REQUEST_BYTES = 6 * 1024 * 1024  # 5 MB plan uploads plus envelope overhead
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Creating a session is the one mutation without a CSRF token yet (ADR-0013); login CSRF on an
# anonymous/local session grants nothing.
CSRF_EXEMPT = frozenset({("POST", "/api/v1/session")})

log = get_logger("querycure.api")


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _envelope(err: QueryCureError, request: Request) -> JSONResponse:
    return JSONResponse(
        err.to_envelope(request_id=_request_id(request)),
        status_code=err.status,
        headers=err.headers,
    )


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
    """Plain ASGI (not BaseHTTPMiddleware) so exceptions are never wrapped in task groups. Also
    counts responses by status class. It runs inside CORS and the body limit, so their own
    refusals are not counted; CSRF refusals are."""

    def __init__(self, app: ASGIApp, *, metrics: ProcessMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                self.metrics.response(message["status"])
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


class SecurityHeadersMiddleware:
    """Headers for every API response (SECURITY §9). JSON is never framed, sniffed or cached
    (responses are per-user); HSTS only where the API is served over HTTPS (demo profile)."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy", b"frame-ancestors 'none'"),
            (b"cache-control", b"no-store"),
        ]
        if hsts:
            self.headers.append(
                (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers if k not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class CsrfMiddleware:
    """Double-submit token: the `qc_csrf` cookie must equal the X-CSRF-Token header."""

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
    """Same envelope as QueryCureError, for framework-raised errors (404, validation, crashes)."""
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
    @app.exception_handler(QueryCureError)
    async def domain_error(request: Request, exc: QueryCureError) -> JSONResponse:
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
        if _database_unreachable(exc):
            log.warning("database_unavailable", exc_info=exc, path=request.url.path)
            return _plain_error(
                request,
                503,
                "SERVICE_UNAVAILABLE",
                "The database is unavailable; try again shortly.",
            )
        log.error("unhandled_error", exc_info=exc, path=request.url.path)
        request.app.state.process_metrics.unhandled_error()
        return _plain_error(request, 500, "INTERNAL_ERROR", "Internal error.")


def _database_unreachable(exc: Exception) -> bool:
    """Connection-level failures (no SQLSTATE: refused, DNS, TLS, dropped) and pool exhaustion
    are retryable outages, not bugs. Statement errors carry a SQLSTATE and stay 500."""
    if isinstance(exc, sa_exc.TimeoutError):
        return True
    if isinstance(exc, sa_exc.OperationalError | sa_exc.InterfaceError):
        return exc.connection_invalidated or getattr(exc.orig, "sqlstate", None) is None
    return False
