"""arq worker entrypoint.

Run with: ``arq app.worker.WorkerSettings``

Jobs:
  - ``refresh_source(source_id)`` — fetch + parse + replace a source's channels,
    then (re)discover its EPG source and queue that too
  - ``refresh_epg_source(epg_source_id)`` — conditional GET + parse XMLTV +
    replace programmes, then queue a TMDB enrichment pass
  - ``enrich_epg(tenant_id)`` — warm the TMDB cache for the coming week
  - ``enrich_programme(tenant_id, programme_id)`` — on-demand single enrichment
  - ``activity_notification(tenant_id, category, title, body)`` — push a queued
    user-action notification (Remind Me / Watch title / Play / watchlist removal)
  - ``sweep`` (cron, every 15 min) — enqueue refreshes that are due
  - ``reminders`` (cron, every 5 min) — email + push watchlist reminders
  - ``source_alerts`` (cron, every 15 min) — email + push a tenant when a
    source's health changes (broke, went stale, recovered)
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, ClassVar, get_args

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.auth.email import send_email
from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker
from app.logging import configure_logging, get_logger
from app.models.epg import EpgSource
from app.models.source import Channel, Source
from app.models.tenant import Tenant
from app.models.user import User
from app.services import epg as epg_svc
from app.services import notify as notify_svc
from app.services import sources as src_svc
from app.services import tmdb as tmdb_svc
from app.services import watchlist as watchlist_svc

_log = get_logger("worker")


def _now() -> datetime:
    return datetime.now(UTC)


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


async def activity_notification(
    _ctx: dict[str, Any], tenant_id: str, category: str, title: str, body: str
) -> None:
    """Deliver a queued user-action push (enqueued by ``app.queue``). The
    per-tenant opt-in is re-checked here — the flag is the source of truth, not
    whatever was true when the job was enqueued."""
    if category not in get_args(notify_svc.ActivityCategory):
        _log.warning("worker.activity_notification.bad_category", category=category)
        return
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, uuid.UUID(tenant_id))
        if tenant is None:
            return
        await notify_svc.notify_activity(
            session,
            tenant,
            category,  # type: ignore[arg-type]  # narrowed by the get_args guard above
            notify_svc.Notification(title=title, body=body),
        )


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


async def reminders(ctx: dict[str, Any]) -> None:
    """Email watchlist reminders whose lead window has opened. Runs every 5 min;
    the send-once ledger keeps a title watch from double-emailing an airing."""
    now = _now()
    sent = 0
    pushed = 0
    pushed_keys: set[tuple[uuid.UUID, str]] = set()
    async with get_sessionmaker()() as session:
        due = await watchlist_svc.due_reminders(session, now=now)
        for r in due:
            channel = await session.get(Channel, r.channel_id)
            if channel is None:
                continue
            local_start, _stop, tz = await epg_svc.local_times(
                session, channel, r.start_utc, r.stop_utc
            )
            when = local_start.strftime("%a %d %b, %H:%M")
            await send_email(
                to=r.user.email,
                subject=f"Reminder: {r.title} on {channel.name}",
                body_text=(
                    f"{r.title}\n{channel.name} — {when} ({tz})\n\n"
                    f"Starting in about {r.item.lead_minutes} minutes.\n"
                    f"{get_settings().public_origin}\n"
                ),
            )
            # Push targets are tenant-level; two users watching the same airing
            # must not double-notify the tenant's devices.
            push_key = (r.item.tenant_id, r.key)
            if push_key not in pushed_keys:
                pushed_keys.add(push_key)
                pushed += await notify_svc.dispatch(
                    session,
                    r.item.tenant_id,
                    notify_svc.Notification(
                        title=f"Reminder: {r.title}",
                        body=(
                            f"{channel.name} — {when} ({tz})\n"
                            f"Starting in about {r.item.lead_minutes} minutes."
                        ),
                    ),
                    event="reminders",
                )
            await watchlist_svc.mark_sent(session, r.item, key=r.key, now=now)
            sent += 1
        await watchlist_svc.prune(session, now=now)
        await session.commit()
    if sent:
        _log.info("worker.reminders", sent=sent, pushed=pushed)


def _alert_email(changes: list[src_svc.HealthChange], origin: str) -> tuple[str, str]:
    bad = [c for c in changes if c.health != "ok"]
    if len(changes) == 1:
        c = changes[0]
        verb = "recovered" if c.health == "ok" else "needs attention"
        subject = f"tvtimes: {c.source.display_name} {verb}"
    elif not bad:
        subject = f"tvtimes: {len(changes)} sources recovered"
    else:
        subject = f"tvtimes: {len(bad)} source(s) need attention"
    lines = [f"- {c.source.display_name} ({c.source.kind.value}): {c.reason}" for c in changes]
    body = "\n".join(lines) + f"\n\nManage them: {origin}/sources\n"
    return subject, body


async def source_alerts(ctx: dict[str, Any]) -> None:
    """Email a tenant when one of its sources breaks, goes stale, or recovers.
    Runs every 15 min; a per-source ``alerted_health`` marker means one email
    per transition, not one per tick."""
    now = _now()
    emails = 0
    pushed = 0
    async with get_sessionmaker()() as session:
        changes = await src_svc.scan_health_changes(session, now=now)
        by_tenant: dict[uuid.UUID, list[src_svc.HealthChange]] = defaultdict(list)
        for c in changes:
            by_tenant[c.source.tenant_id].append(c)
        origin = get_settings().public_origin
        for tenant_id, group in by_tenant.items():
            tenant = await session.get(Tenant, tenant_id)
            if tenant is None or not tenant.source_alerts_enabled:
                continue  # markers are still stamped, so re-enabling won't replay
            subject, body = _alert_email(group, origin)
            # Push fires per tenant (targets are tenant-level), independent of
            # whether any user has a verified email address.
            pushed += await notify_svc.dispatch(
                session,
                tenant_id,
                notify_svc.Notification(title=subject, body=body),
                event="source_alerts",
            )
            users = list(
                await session.scalars(
                    select(User).where(
                        User.tenant_id == tenant_id, User.email_verified_at.is_not(None)
                    )
                )
            )
            for u in users:
                await send_email(to=u.email, subject=subject, body_text=body)
                emails += 1
        await session.commit()  # persist the alerted_health stamps
    if changes:
        _log.info("worker.source_alerts", changes=len(changes), emails=emails, pushed=pushed)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        refresh_source,
        refresh_epg_source,
        enrich_epg,
        enrich_programme,
        activity_notification,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(sweep, minute=set(range(0, 60, 15))),
        cron(reminders, minute=set(range(0, 60, 5))),
        # a few minutes after the sweep, so it sees this cycle's refresh results
        cron(source_alerts, minute=set(range(7, 60, 15))),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
