"""EPG source CRUD and refresh (conditional GET → parse XMLTV → replace
programmes), plus channel-schedule reads with timezone/clock-shift applied."""

from __future__ import annotations

import contextlib
import uuid
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.errors import SourceError, SourceUnreachable
from app.ingest.ssrf import assert_allowed_url, fetch_bytes
from app.ingest.xmltv import (
    FEED_SUFFIX_RE,
    ParsedGuide,
    is_movie,
    normalize_name,
    parse_xmltv,
)
from app.logging import get_logger
from app.models.epg import EpgSource, EpgStatus, Programme
from app.models.source import Channel, Source
from app.models.tenant import Tenant

_log = get_logger("services.epg")

WINDOW_PAST = timedelta(days=1)
WINDOW_FUTURE = timedelta(days=14)


class EpgSourceNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


# --- CRUD -----------------------------------------------------------------------


async def create_epg_source(session: AsyncSession, *, tenant_id: uuid.UUID, url: str) -> EpgSource:
    url = url.strip()
    # A transient DNS failure is left for the refresh to report.
    with contextlib.suppress(SourceUnreachable):
        await assert_allowed_url(url)
    existing = await session.scalar(
        select(EpgSource).where(EpgSource.tenant_id == tenant_id, EpgSource.url == url)
    )
    if existing is not None:
        return existing
    row = EpgSource(tenant_id=tenant_id, url=url, last_status=EpgStatus.pending)
    session.add(row)
    await session.flush()
    return row


async def ensure_epg_source_for(
    session: AsyncSession, source: Source, *, reset_cache: bool = False
) -> EpgSource | None:
    """Keep an ``epg_source`` row in step with a Source's discovered EPG URL.

    ``reset_cache=True`` clears the conditional-GET state so the next refresh
    re-downloads and re-parses the feed even if it is byte-identical — needed
    after the source's channels were rebuilt, since the programmes were
    matched to the *old* channel ids.
    """
    url = (source.epg_url or "").strip()
    existing = await session.scalar(select(EpgSource).where(EpgSource.source_id == source.id))
    if not url:
        if existing is not None:
            await session.delete(existing)
        return None
    if existing is None:
        existing = EpgSource(
            tenant_id=source.tenant_id,
            source_id=source.id,
            url=url,
            last_status=EpgStatus.pending,
        )
        session.add(existing)
        await session.flush()
    elif existing.url != url:
        existing.url = url
        existing.etag = existing.last_modified = None
        existing.last_status = EpgStatus.pending
    elif reset_cache:
        existing.etag = existing.last_modified = None
    return existing


async def list_epg_sources(session: AsyncSession, tenant_id: uuid.UUID) -> Sequence[EpgSource]:
    rows = await session.scalars(
        select(EpgSource)
        .where(EpgSource.tenant_id == tenant_id)
        .order_by(EpgSource.created_at.desc())
    )
    return list(rows)


async def get_epg_source(
    session: AsyncSession, tenant_id: uuid.UUID, epg_source_id: uuid.UUID
) -> EpgSource:
    row = await session.get(EpgSource, epg_source_id)
    if row is None or row.tenant_id != tenant_id:
        raise EpgSourceNotFound
    return row


async def delete_epg_source(session: AsyncSession, row: EpgSource) -> None:
    await session.delete(row)


# --- refresh ------------------------------------------------------------------


async def _channel_index(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, list[uuid.UUID]]:
    """Map XMLTV channel keys -> our channel ids. Keys: raw tvg-id, the
    ``@feed``-stripped tvg-id, and normalised display / tvg names. A key can
    fan out to several channels (e.g. an East and West feed that share a
    tvg-id) — each then gets its own copy of the programmes."""
    index: dict[str, list[uuid.UUID]] = {}
    rows = await session.scalars(select(Channel).where(Channel.tenant_id == tenant_id))
    for ch in rows:
        keys: list[str] = []
        if ch.ext_id:
            # tvg-id / XMLTV id casing is wildly inconsistent between feeds
            # (``TCM.us`` vs ``tcm.us``) — match case-insensitively.
            keys.append(ch.ext_id.lower())
            keys.append(FEED_SUFFIX_RE.sub("", ch.ext_id).lower())
        keys.append(normalize_name(ch.name))
        if ch.tvg_name:
            keys.append(normalize_name(ch.tvg_name))
        for key in keys:
            if not key:
                continue
            bucket = index.setdefault(key, [])
            if ch.id not in bucket:
                bucket.append(ch.id)
    return index


def _resolve_channels(
    xmltv_id: str, guide: ParsedGuide, index: dict[str, list[uuid.UUID]]
) -> list[uuid.UUID]:
    lowered = xmltv_id.lower()
    if lowered in index:
        return index[lowered]
    stripped = FEED_SUFFIX_RE.sub("", xmltv_id).lower()
    if stripped in index:
        return index[stripped]
    channel = guide.channels.get(xmltv_id)
    if channel is not None:
        for name in channel.display_names:
            hit = index.get(normalize_name(name))
            if hit:
                return hit
    return []


async def refresh_epg_source(session: AsyncSession, epg_source: EpgSource) -> None:
    """Never raises: failures land in ``last_status`` / ``last_error``."""
    url = epg_source.url.strip()
    if not url and epg_source.source_id is not None:
        source = await session.get(Source, epg_source.source_id)
        url = (source.epg_url or "").strip() if source else ""
    if not url:
        epg_source.last_status = EpgStatus.error
        epg_source.last_error = "This source has no EPG URL."
        epg_source.last_fetched_at = _now()
        return

    try:
        result = await fetch_bytes(
            url, etag=epg_source.etag, last_modified=epg_source.last_modified
        )
    except SourceError as exc:
        epg_source.last_status = EpgStatus.error
        epg_source.last_error = exc.message
        epg_source.last_fetched_at = _now()
        _log.warning("epg.fetch_failed", epg_source_id=str(epg_source.id), error=exc.message)
        return

    epg_source.last_fetched_at = _now()
    if result.status == 304:
        epg_source.last_status = EpgStatus.ok
        epg_source.last_error = None
        return

    try:
        guide = parse_xmltv(result.body)
    except Exception:  # a malformed feed must not wedge the worker
        epg_source.last_status = EpgStatus.error
        epg_source.last_error = "The XMLTV feed could not be parsed."
        _log.exception("epg.parse_failed", epg_source_id=str(epg_source.id))
        return

    index = await _channel_index(session, epg_source.tenant_id)
    now = _now()
    lo, hi = now - WINDOW_PAST, now + WINDOW_FUTURE
    group_by_channel = await _channel_groups(session, epg_source.tenant_id)

    await session.execute(delete(Programme).where(Programme.epg_source_id == epg_source.id))
    count = 0
    for prog in guide.programmes:
        if not (lo <= prog.start <= hi):
            continue
        for channel_id in _resolve_channels(prog.channel_id, guide, index):
            session.add(
                Programme(
                    tenant_id=epg_source.tenant_id,
                    channel_id=channel_id,
                    epg_source_id=epg_source.id,
                    start_utc=prog.start,
                    stop_utc=prog.stop,
                    title=prog.title[:500] or "(untitled)",
                    sub_title=(prog.sub_title or None) and prog.sub_title[:500],
                    description=prog.description,
                    categories=prog.categories,
                    episode_num=(prog.episode_num or None) and prog.episode_num[:64],
                    year=prog.year,
                    icon_url=prog.icon_url,
                    director=prog.director,
                    is_movie=is_movie(prog.categories, group_by_channel.get(channel_id)),
                )
            )
            count += 1

    epg_source.programme_count = count
    epg_source.etag = result.etag
    epg_source.last_modified = result.last_modified
    epg_source.last_status = EpgStatus.ok
    epg_source.last_error = None
    _log.info("epg.refreshed", epg_source_id=str(epg_source.id), programmes=count)


async def _channel_groups(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[uuid.UUID, str | None]:
    result = await session.execute(
        select(Channel.id, Channel.group_title).where(Channel.tenant_id == tenant_id)
    )
    groups: dict[uuid.UUID, str | None] = {}
    for cid, group in result.all():
        groups[cid] = group
    return groups


async def due_epg_sources(session: AsyncSession) -> list[uuid.UUID]:
    now = _now()
    rows = await session.scalars(select(EpgSource))
    due: list[uuid.UUID] = []
    for s in rows:
        if (
            s.last_fetched_at is None
            or s.last_fetched_at + timedelta(minutes=s.refresh_interval_minutes) < now
        ):
            due.append(s.id)
    return due


# --- schedule read ----------------------------------------------------------


def _shift_seconds(channel: Channel, source: Source | None) -> int:
    return channel.clock_shift_seconds or (source.clock_shift_seconds if source else 0)


async def local_times(
    session: AsyncSession, channel: Channel, start_utc: datetime, stop_utc: datetime
) -> tuple[datetime, datetime, str]:
    """Resolve one programme's UTC start/stop into the channel's display tz."""
    source = await session.get(Source, channel.source_id)
    override = source.timezone_override if source and source.timezone_override else None
    if override is None:
        tenant = await session.get(Tenant, channel.tenant_id)
        override = tenant.default_timezone if tenant else "UTC"
    tz, tz_name = _resolve_tz(override)
    shift = timedelta(seconds=_shift_seconds(channel, source))
    return (start_utc + shift).astimezone(tz), (stop_utc + shift).astimezone(tz), tz_name


async def channel_schedule(
    session: AsyncSession,
    channel: Channel,
    *,
    start: datetime,
    end: datetime,
) -> tuple[list[tuple[Programme, datetime, datetime]], str]:
    """Return ``(programme, local_start, local_stop)`` triples overlapping
    ``[start, end)`` and the resolved IANA timezone name."""
    source = await session.get(Source, channel.source_id)
    tz_name = source.timezone_override if source and source.timezone_override else None
    if tz_name is None:
        tenant = await session.get(Tenant, channel.tenant_id)
        tz_name = tenant.default_timezone if tenant else "UTC"
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        tz, tz_name = zoneinfo.ZoneInfo("UTC"), "UTC"
    shift = timedelta(seconds=_shift_seconds(channel, source))

    rows = await session.scalars(
        select(Programme)
        .where(
            Programme.channel_id == channel.id,
            Programme.stop_utc > start,
            Programme.start_utc < end,
        )
        .order_by(Programme.start_utc)
    )
    out: list[tuple[Programme, datetime, datetime]] = []
    for p in rows:
        out.append(
            (
                p,
                (p.start_utc + shift).astimezone(tz),
                (p.stop_utc + shift).astimezone(tz),
            )
        )
    return out, tz_name


@dataclass(slots=True)
class GuideRow:
    channel: Channel
    timezone: str
    programmes: list[tuple[Programme, datetime, datetime]]


def _resolve_tz(name: str) -> tuple[zoneinfo.ZoneInfo, str]:
    try:
        return zoneinfo.ZoneInfo(name), name
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC"), "UTC"


async def guide(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    source_id: uuid.UUID | None = None,
    group: str | None = None,
    channel_ids: Sequence[uuid.UUID] | None = None,
    limit: int = 300,
) -> list[GuideRow]:
    """Programmes for many channels in ``[start, end)``, one row per channel,
    each with times already resolved to that channel's display timezone."""
    stmt = select(Channel).where(Channel.tenant_id == tenant_id)
    if source_id is not None:
        stmt = stmt.where(Channel.source_id == source_id)
    if group:
        stmt = stmt.where(Channel.group_title == group)
    if channel_ids:
        stmt = stmt.where(Channel.id.in_(list(channel_ids)))
    stmt = stmt.order_by(
        Channel.number.is_(None), Channel.number, Channel.sort_order, Channel.name
    ).limit(limit)
    channels = list(await session.scalars(stmt))
    if not channels:
        return []

    source_ids = {c.source_id for c in channels}
    sources = {
        s.id: s for s in await session.scalars(select(Source).where(Source.id.in_(source_ids)))
    }
    tenant = await session.get(Tenant, tenant_id)
    default_tz = tenant.default_timezone if tenant else "UTC"

    ids = [c.id for c in channels]
    programmes = await session.scalars(
        select(Programme)
        .where(
            Programme.channel_id.in_(ids),
            Programme.stop_utc > start,
            Programme.start_utc < end,
        )
        .order_by(Programme.start_utc)
    )
    by_channel: dict[uuid.UUID, list[Programme]] = {cid: [] for cid in ids}
    for p in programmes:
        by_channel[p.channel_id].append(p)

    rows: list[GuideRow] = []
    for channel in channels:
        source = sources.get(channel.source_id)
        override = source.timezone_override if source else None
        tz, tz_name = _resolve_tz(override or default_tz)
        shift = timedelta(seconds=_shift_seconds(channel, source))
        rows.append(
            GuideRow(
                channel=channel,
                timezone=tz_name,
                programmes=[
                    (p, (p.start_utc + shift).astimezone(tz), (p.stop_utc + shift).astimezone(tz))
                    for p in by_channel[channel.id]
                ],
            )
        )
    return rows


async def programme_counts(session: AsyncSession, epg_source_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Programme)
            .where(Programme.epg_source_id == epg_source_id)
        )
        or 0
    )
