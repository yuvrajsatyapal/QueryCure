import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure import __version__
from querycure.api.middleware import (
    CsrfMiddleware,
    MaxBodySizeMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    install_error_handlers,
)
from querycure.api.process_metrics import ProcessMetrics
from querycure.api.routers import (
    artifacts,
    auth,
    connections,
    demo,
    health,
    inspect,
    investigations,
    metrics,
    optimization,
    reports,
    runs,
    session,
    workloads,
)
from querycure.api.routers import (
    settings as settings_router,
)
from querycure.core.config import Profile, Settings, WorkerMode, serving_problems
from querycure.core.logging import configure_logging
from querycure.db.engine import make_engine

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(level=settings.log_level)
    # Tests inject an engine; a real deployment never does, so it must be fully configured.
    if engine is None and (problems := serving_problems(settings)):
        raise RuntimeError("refusing to start: " + "; ".join(problems))
    owns_engine = engine is None and settings.database_url is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if owns_engine and settings.database_url is not None:
            app.state.engine = make_engine(
                settings.database_url.get_secret_value(),
                **settings.engine_options(),
            )
        embedded: tuple[Any, asyncio.Task[None]] | None = None
        if settings.worker_mode is WorkerMode.EMBEDDED and app.state.engine is not None:
            # Single-container demo (DEPLOYMENT §1): the job loop runs in this process.
            from querycure.worker.__main__ import build_worker, serve
            from querycure.worker.heartbeat import identity

            worker, sandbox = build_worker(app.state.engine, settings)
            me = identity(worker.worker_id, bench_path=settings.bench_path if sandbox else None)
            embedded = (
                worker,
                asyncio.create_task(serve(worker, app.state.engine, sandbox, identity=me)),
            )
        try:
            yield
        finally:
            if embedded is not None:
                await embedded[0].stop()  # drains in-flight jobs for the configured grace
                await embedded[1]
            if app.state.event_hub is not None:
                await app.state.event_hub.close()
            if getattr(app.state, "oauth_http", None) is not None:
                await app.state.oauth_http.aclose()
            if owns_engine and app.state.engine is not None:
                await app.state.engine.dispose()

    app = FastAPI(
        title="QueryCure",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        # The interactive docs page is a local-development convenience; the public demo
        # keeps only the machine-readable schema.
        docs_url=f"{API_PREFIX}/docs" if settings.profile is Profile.LOCAL else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.process_metrics = ProcessMetrics()
    app.state.engine = engine
    app.state.event_hub = None
    install_error_handlers(app)
    # Starlette runs the last-added middleware first:
    # security headers → body limit → CORS → request id → CSRF.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware, metrics=app.state.process_metrics)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        # Idempotency-Key: run creation, replays; Last-Event-ID: SSE reconnects.
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "Last-Event-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(MaxBodySizeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.profile is not Profile.LOCAL)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(metrics.router, prefix=API_PREFIX)
    app.include_router(demo.router, prefix=API_PREFIX)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(auth.github_router, prefix=API_PREFIX)
    app.include_router(auth.google_router, prefix=API_PREFIX)
    app.include_router(connections.router, prefix=API_PREFIX)
    app.include_router(inspect.router, prefix=API_PREFIX)
    app.include_router(workloads.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(optimization.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(investigations.router, prefix=API_PREFIX)
    app.include_router(artifacts.router, prefix=API_PREFIX)
    app.include_router(settings_router.router, prefix=API_PREFIX)
    return app


app = create_app()
