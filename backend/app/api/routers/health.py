"""Liveness / readiness probes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_session

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/readyz", response_model=Readiness)
async def readyz(session: Annotated[AsyncSession, Depends(get_session)]) -> Readiness:
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pragma: no cover - exercised via failure injection
        db_ok = False
    return Readiness(status="ready" if db_ok else "degraded", database=db_ok)
