"""arq worker entrypoint.

Run with: ``arq app.worker.WorkerSettings``

Jobs:
  - ``refresh_source(source_id)`` — fetch + parse + replace a source's channels,
    then (re)discover its EPG source and queue that too
  - ``refresh_epg_source(epg_source_id)`` — conditional GET + parse XMLTV +
    replace programmes, then queue a TMDB enrichment pass
  - ``enrich_epg(tenant_id)`` — warm the TMDB cache for the coming week
  - ``enrich_programme(tenant_id, programme_id)`` — on-demand single enrichment
  - ``sweep`` (cron, every 15 min) — enqueue refreshes that are due
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker
from app.logging import configure_logging, get_logger
from app.models.epg import EpgSource
from app.models.source import Source
from app.services import epg as epg_svc
from app.services import sources as src_svc
from app.services import tmdb as tmdb_svc

_log = get_logger("worker")


async def startup(_ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.is_prod)
    _log.info("worker.startup", env=settings.env)


async def shutdown(_ctx: dict[str, Any]) -> None:
    await dispose_engine()
    _log.info("worker.shutdown")


async def refresh_source(ctx: dict[str, Any], source_id: str, force_epg: bool = False) -> None:
    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        if source is None:
            _log.warning("worker.refresh.missing", source_id=source_id)
            return
        channels_changed = await src_svc.refresh_source(session, source)
        epg_source = await epg_svc.ensure_epg_source_for(
            session, source, reset_cache=channels_changed or force_epg
        )
        await session.commit()
    if epg_source is not None:
        await ctx["redis"].enqueue_job("refresh_epg_source", str(epg_source.id))


async def refresh_epg_source(ctx: dict[str, Any], epg_source_id: str) -> None:
    async with get_sessionmaker()() as session:
        row = await session.get(EpgSource, uuid.UUID(epg_source_id))
        if row is None:
            _log.warning("worker.epg.missing", epg_source_id=epg_source_id)
            return
        await epg_svc.refresh_epg_source(session, row)
        tenant_id = row.tenant_id
        await session.commit()
    await ctx["redis"].enqueue_job("enrich_epg", str(tenant_id))


async def enrich_epg(_ctx: dict[str, Any], tenant_id: str) -> None:
    async with get_sessionmaker()() as session:
        token = await tmdb_svc.token_for(session, uuid.UUID(tenant_id))
        if token is None:
            return
        await tmdb_svc.enrich_epg_window(session, uuid.UUID(tenant_id), token)
        await session.commit()


async def enrich_programme(_ctx: dict[str, Any], tenant_id: str, programme_id: str) -> None:
    async with get_sessionmaker()() as session:
        await tmdb_svc.enrich_programme(session, uuid.UUID(tenant_id), uuid.UUID(programme_id))
        await session.commit()


async def sweep(ctx: dict[str, Any]) -> None:
    async with get_sessionmaker()() as session:
        due_sources = await src_svc.due_for_refresh(session)
        due_epg = await epg_svc.due_epg_sources(session)
    for sid in due_sources:
        await ctx["redis"].enqueue_job("refresh_source", str(sid))
    for eid in due_epg:
        await ctx["redis"].enqueue_job("refresh_epg_source", str(eid))
    if due_sources or due_epg:
        _log.info("worker.sweep", sources=len(due_sources), epg=len(due_epg))


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        refresh_source,
        refresh_epg_source,
        enrich_epg,
        enrich_programme,
    ]
    cron_jobs: ClassVar[list[Any]] = [cron(sweep, minute=set(range(0, 60, 15)))]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
