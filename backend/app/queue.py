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


async def _enqueue(job: str, *args: object) -> None:
    """Best effort: a queue outage must not fail the API call that triggered it
    (the periodic sweep will pick the work up)."""
    try:
        pool = await get_pool()
        await pool.enqueue_job(job, *args)
    except Exception as exc:
        _log.warning("queue.enqueue_failed", job=job, error=str(exc))


async def enqueue_source_refresh(source_id: uuid.UUID, *, force_epg: bool = False) -> None:
    """``force_epg`` re-parses the EPG even if the feed is unchanged — used for
    the manual "Refresh" button so a user can always rebuild stale programmes."""
    await _enqueue("refresh_source", str(source_id), force_epg)


async def enqueue_epg_refresh(epg_source_id: uuid.UUID) -> None:
    await _enqueue("refresh_epg_source", str(epg_source_id))


async def enqueue_programme_enrich(tenant_id: uuid.UUID, programme_id: uuid.UUID) -> None:
    await _enqueue("enrich_programme", str(tenant_id), str(programme_id))


async def enqueue_activity_notification(
    tenant_id: uuid.UUID, category: str, title: str, body: str
) -> None:
    """Push a user-action notification (Remind Me / Watch title / Play / removal)
    to the tenant's targets. Done off the request path — the Apprise round-trip
    shouldn't add latency to the click that triggered it. The worker re-checks
    the per-tenant opt-in, so a stale enqueue is harmless."""
    await _enqueue("activity_notification", str(tenant_id), category, title, body)
