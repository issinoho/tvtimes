"""arq worker entrypoint.

Run with: ``arq app.worker.WorkerSettings``

Jobs:
  - ``refresh_source(source_id)`` — fetch + parse + replace a source's channels
  - ``sweep_sources`` (cron, every 15 min) — enqueue refreshes that are due
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker
from app.logging import configure_logging, get_logger
from app.models.source import Source
from app.services import sources as svc

_log = get_logger("worker")


async def startup(_ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.is_prod)
    _log.info("worker.startup", env=settings.env)


async def shutdown(_ctx: dict[str, Any]) -> None:
    await dispose_engine()
    _log.info("worker.shutdown")


async def refresh_source(_ctx: dict[str, Any], source_id: str) -> None:
    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        if source is None:
            _log.warning("worker.refresh.missing", source_id=source_id)
            return
        await svc.refresh_source(session, source)
        await session.commit()


async def sweep_sources(ctx: dict[str, Any]) -> None:
    async with get_sessionmaker()() as session:
        due = await svc.due_for_refresh(session)
    for source_id in due:
        await ctx["redis"].enqueue_job("refresh_source", str(source_id))
    if due:
        _log.info("worker.sweep", enqueued=len(due))


class WorkerSettings:
    functions: ClassVar[list[Any]] = [refresh_source]
    cron_jobs: ClassVar[list[Any]] = [cron(sweep_sources, minute=set(range(0, 60, 15)))]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
