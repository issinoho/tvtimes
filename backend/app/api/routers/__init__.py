"""API routers. Each phase mounts its own; see ``app.main.create_app``."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import (
    account,
    auth,
    connector,
    connectors,
    epg,
    exports,
    health,
    hero,
    sources,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(sources.router)
api_router.include_router(epg.router)
api_router.include_router(exports.router)
api_router.include_router(hero.router)
api_router.include_router(connectors.router)
api_router.include_router(connector.router)

__all__ = ["api_router"]
