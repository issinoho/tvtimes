"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routers import api_router
from app.config import get_settings
from app.db import dispose_engine
from app.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.is_prod)
    log = get_logger("app")
    log.info("startup", env=settings.env, rp_id=settings.webauthn_rp_id)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="tvtimes API",
        version=__version__,
        description="Multi-tenant TV schedule (EPG) service.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # In prod the SPA and API share an origin (served under /api) so CORS is a
    # dev-only convenience for the Vite dev server.
    if not settings.is_prod:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.public_origin, "http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
