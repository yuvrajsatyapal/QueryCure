from fastapi import FastAPI

from querydoctor import __version__
from querydoctor.api.routers import health

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="QueryDoctor AI",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
