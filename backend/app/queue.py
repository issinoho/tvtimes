"""Thin wrapper around the arq queue so API handlers can enqueue background
work without holding a pool themselves."""

from __future__ import annotations

import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings
from app.logging import get_logger

_log = get_logger("queue")
_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_source_refresh(source_id: uuid.UUID) -> None:
    """Best effort: a queue outage must not fail the API call that triggered it
    (the periodic sweep will pick the source up)."""
    try:
        pool = await get_pool()
        await pool.enqueue_job("refresh_source", str(source_id))
    except Exception as exc:
        _log.warning("queue.enqueue_failed", job="refresh_source", error=str(exc))
