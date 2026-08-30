"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api.routers import api_router
from app.auth.errors import AuthError, MfaRequired
from app.auth.ratelimit import limiter
from app.config import get_settings
from app.db import dispose_engine
from app.ingest.errors import SourceError
from app.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.assert_production_ready()
    configure_logging(settings.log_level, json=settings.is_prod)
    log = get_logger("app")
    log.info("startup", env=settings.env, rp_id=settings.webauthn_rp_id)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("shutdown")


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _auth_error(_request: Request, exc: AuthError) -> JSONResponse:
        body: dict[str, object] = {"code": exc.code, "message": exc.message}
        if isinstance(exc, MfaRequired):
            body["mfa_token"] = exc.mfa_token
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(SourceError)
    async def _source_error(_request: Request, exc: SourceError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"code": "source_error", "message": exc.message}
        )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"code": "rate_limited", "message": "Too many requests. Slow down."},
        )


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
    app.state.limiter = limiter

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

    _install_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: str) -> None:
    """Serve the built SPA from the same origin as the API. Real files (hashed
    assets, the service worker, icons) are returned directly; everything else
    falls back to ``index.html`` so client-side routes work on a hard refresh.
    Registered after the ``/api`` router so API routes always win."""
    root = Path(static_dir)
    if not static_dir or not (root / "index.html").is_file():
        return

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path in {"openapi.json", "docs", "redoc"}:
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and root.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
