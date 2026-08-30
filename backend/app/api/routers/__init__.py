"""API routers. Each phase mounts its own; see ``app.main.create_app``."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router"]
