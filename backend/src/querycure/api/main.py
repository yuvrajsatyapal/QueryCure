from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure import __version__
from querycure.api.middleware import (
    CsrfMiddleware,
    MaxBodySizeMiddleware,
    RequestIdMiddleware,
    install_error_handlers,
)
from querycure.api.routers import (
    artifacts,
    connections,
    health,
    inspect,
    investigations,
    runs,
    session,
    workloads,
)
from querycure.api.routers import (
    settings as settings_router,
)
from querycure.core.config import Settings
from querycure.core.logging import configure_logging
from querycure.db.engine import make_engine

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(level=settings.log_level)
    owns_engine = engine is None and settings.database_url is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if owns_engine and settings.database_url is not None:
            app.state.engine = make_engine(settings.database_url.get_secret_value())
        try:
            yield
        finally:
            if app.state.event_hub is not None:
                await app.state.event_hub.close()
            if owns_engine and app.state.engine is not None:
                await app.state.engine.dispose()

    app = FastAPI(
        title="QueryCure",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.event_hub = None
    install_error_handlers(app)
    # Starlette runs the last-added middleware first: body limit → CORS → request id → CSRF.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(MaxBodySizeMiddleware)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(connections.router, prefix=API_PREFIX)
    app.include_router(inspect.router, prefix=API_PREFIX)
    app.include_router(workloads.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(investigations.router, prefix=API_PREFIX)
    app.include_router(artifacts.router, prefix=API_PREFIX)
    app.include_router(settings_router.router, prefix=API_PREFIX)
    return app


app = create_app()
