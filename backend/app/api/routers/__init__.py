"""API routers. Each phase mounts its own; see ``app.main.create_app``."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import account, auth, health, sources

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(sources.router)

__all__ = ["api_router"]
