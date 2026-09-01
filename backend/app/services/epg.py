"""EPG source CRUD and refresh (conditional GET → parse XMLTV → replace
programmes), plus channel-schedule reads with timezone/clock-shift applied."""

from __future__ import annotations

import contextlib
import uuid
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
from app.models.tmdb import MediaType, TmdbEnrichment
from app.services.tmdb import cache_key

_log = get_logger("services.epg")

WINDOW_PAST = timedelta(days=1)
WINDOW_FUTURE = timedelta(days=14)

# A channel's (or its source's) clock-shift correction moves its wall-clock, so
# a programme's *effective* airtime for any window / "now" comparison is
# ``start_utc + shift``. Windowed queries filter on raw ``start_utc`` for index
# use, then widen by this bound (the schema cap on ``clock_shift_seconds``) and
# re-test each row against the shifted interval in Python.
MAX_CLOCK_SHIFT = timedelta(seconds=86_400)


class EpgSourceNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


# --- CRUD -----------------------------------------------------------------------


async def create_epg_source(session: AsyncSession, *, tenant_id: uuid.UUID, url: str) -> EpgSource:
    url = url.strip()
    # A transient DNS failure is left for the refresh to report. A LAN URL the
    # operator has allow-listed (TVTIMES_FETCH_ALLOWLIST) is permitted.
    with contextlib.suppress(SourceUnreachable):
        await assert_allowed_url(url, allowlist=get_settings().fetch_allowlist_entries)
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

    # The window is in wall-clock terms; a shifted channel's rows land in it
    # when ``start_utc + shift`` does, i.e. raw ``start_utc`` in [start-shift, end-shift).
    rows = await session.scalars(
        select(Programme)
        .where(
            Programme.channel_id == channel.id,
            Programme.stop_utc > start - shift,
            Programme.start_utc < end - shift,
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


def resolve_display_tz(source: Source | None, default_tz: str) -> tuple[zoneinfo.ZoneInfo, str]:
    """The zone a channel's programmes render in: per-source override, else the
    tenant default, else UTC. Shared by the guide grid and the XMLTV export so
    both agree on the wall-clock times."""
    override = source.timezone_override if source and source.timezone_override else None
    return _resolve_tz(override or default_tz)


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
    stmt = select(Channel).join(Source, Channel.source_id == Source.id)
    stmt = stmt.where(Channel.tenant_id == tenant_id)
    if source_id is not None:
        stmt = stmt.where(Channel.source_id == source_id)
    if group:
        stmt = stmt.where(Channel.group_title == group)
    if channel_ids:
        stmt = stmt.where(Channel.id.in_(list(channel_ids)))
    # Source order (from the Sources screen) first, then the usual within-source
    # ordering.
    stmt = stmt.order_by(
        Source.sort_rank,
        Channel.number.is_(None),
        Channel.number,
        Channel.sort_order,
        Channel.name,
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
    # Widen by the max clock-shift; each channel's rows are re-tested against
    # the window with its own shift applied, below.
    programmes = await session.scalars(
        select(Programme)
        .where(
            Programme.channel_id.in_(ids),
            Programme.stop_utc > start - MAX_CLOCK_SHIFT,
            Programme.start_utc < end + MAX_CLOCK_SHIFT,
        )
        .order_by(Programme.start_utc)
    )
    by_channel: dict[uuid.UUID, list[Programme]] = {cid: [] for cid in ids}
    for p in programmes:
        by_channel[p.channel_id].append(p)

    rows: list[GuideRow] = []
    for channel in channels:
        source = sources.get(channel.source_id)
        tz, tz_name = resolve_display_tz(source, default_tz)
        shift = timedelta(seconds=_shift_seconds(channel, source))
        kept: list[tuple[Programme, datetime, datetime]] = []
        for p in by_channel[channel.id]:
            s_utc, e_utc = p.start_utc + shift, p.stop_utc + shift
            if e_utc <= start or s_utc >= end:
                continue
            kept.append((p, s_utc.astimezone(tz), e_utc.astimezone(tz)))
        rows.append(GuideRow(channel=channel, timezone=tz_name, programmes=kept))
    return rows


@dataclass(slots=True)
class SearchHit:
    programme: Programme
    channel: Channel
    local_start: datetime
    local_stop: datetime
    timezone: str


async def search_programmes(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    query: str,
    movies_only: bool = False,
    start: datetime,
    end: datetime,
    limit: int = 100,
) -> list[SearchHit]:
    """Programmes whose title / sub-title matches ``query`` (case-insensitive
    substring) and that air within ``[start, end)``, earliest first — one hit
    per airing, times resolved into each channel's display zone."""
    like = f"%{query.strip()}%"
    # Widened by the max clock-shift; re-tested per channel with its own shift.
    stmt = (
        select(Programme)
        .join(Channel, Programme.channel_id == Channel.id)
        .where(
            Programme.tenant_id == tenant_id,
            Programme.stop_utc > start - MAX_CLOCK_SHIFT,
            Programme.start_utc < end + MAX_CLOCK_SHIFT,
            or_(Programme.title.ilike(like), Programme.sub_title.ilike(like)),
        )
        .order_by(Programme.start_utc)
        .limit(limit + 64)
    )
    if movies_only:
        stmt = stmt.where(Programme.is_movie.is_(True))
    programmes = list(await session.scalars(stmt))
    if not programmes:
        return []

    channel_ids = {p.channel_id for p in programmes}
    channels = {
        c.id: c for c in await session.scalars(select(Channel).where(Channel.id.in_(channel_ids)))
    }
    source_ids = {c.source_id for c in channels.values()}
    sources = {
        s.id: s for s in await session.scalars(select(Source).where(Source.id.in_(source_ids)))
    }
    tenant = await session.get(Tenant, tenant_id)
    default_tz = tenant.default_timezone if tenant else "UTC"

    hits: list[SearchHit] = []
    for p in programmes:
        channel = channels[p.channel_id]
        source = sources.get(channel.source_id)
        tz, tz_name = resolve_display_tz(source, default_tz)
        shift = timedelta(seconds=_shift_seconds(channel, source))
        s_utc, e_utc = p.start_utc + shift, p.stop_utc + shift
        if e_utc <= start or s_utc >= end:  # outside the window once its shift is applied
            continue
        hits.append(
            SearchHit(
                programme=p,
                channel=channel,
                local_start=s_utc.astimezone(tz),
                local_stop=e_utc.astimezone(tz),
                timezone=tz_name,
            )
        )
    hits.sort(key=lambda h: (h.local_start, h.channel.name))
    return hits[:limit]


# --- now/next + highlights -------------------------------------------------


def _localize(
    p: Programme, shift: timedelta, tz: zoneinfo.ZoneInfo
) -> tuple[Programme, datetime, datetime]:
    return p, (p.start_utc + shift).astimezone(tz), (p.stop_utc + shift).astimezone(tz)


@dataclass(slots=True)
class NowNext:
    channel: Channel
    timezone: str
    current: tuple[Programme, datetime, datetime] | None
    upcoming: tuple[Programme, datetime, datetime] | None


async def now_next(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    source_id: uuid.UUID | None = None,
    group: str | None = None,
    limit: int = 500,
    now: datetime | None = None,
) -> list[NowNext]:
    """For every channel, the programme on air now and the one after it — times
    in the channel's display zone, channels in the guide's order."""
    now = now or _now()
    stmt = (
        select(Channel)
        .join(Source, Channel.source_id == Source.id)
        .where(Channel.tenant_id == tenant_id)
    )
    if source_id is not None:
        stmt = stmt.where(Channel.source_id == source_id)
    if group:
        stmt = stmt.where(Channel.group_title == group)
    stmt = stmt.order_by(
        Source.sort_rank,
        Channel.number.is_(None),
        Channel.number,
        Channel.sort_order,
        Channel.name,
    ).limit(limit)
    channels = list(await session.scalars(stmt))
    if not channels:
        return []

    sources = {
        s.id: s
        for s in await session.scalars(
            select(Source).where(Source.id.in_({c.source_id for c in channels}))
        )
    }
    tenant = await session.get(Tenant, tenant_id)
    default_tz = tenant.default_timezone if tenant else "UTC"

    ids = [c.id for c in channels]
    # Widened by the max clock-shift; each channel's rows are tested against
    # ``now`` with its own shift applied, below.
    rows = await session.scalars(
        select(Programme)
        .where(
            Programme.channel_id.in_(ids),
            Programme.stop_utc > now - MAX_CLOCK_SHIFT,
            Programme.start_utc < now + timedelta(hours=24) + MAX_CLOCK_SHIFT,
        )
        .order_by(Programme.start_utc)
    )
    by_channel: dict[uuid.UUID, list[Programme]] = {cid: [] for cid in ids}
    for p in rows:
        by_channel[p.channel_id].append(p)

    out: list[NowNext] = []
    for channel in channels:
        source = sources.get(channel.source_id)
        tz, tz_name = resolve_display_tz(source, default_tz)
        shift = timedelta(seconds=_shift_seconds(channel, source))
        current: tuple[Programme, datetime, datetime] | None = None
        upcoming: tuple[Programme, datetime, datetime] | None = None
        for p in by_channel[channel.id]:
            s_utc, e_utc = p.start_utc + shift, p.stop_utc + shift
            if current is None and s_utc <= now < e_utc:
                current = _localize(p, shift, tz)
            elif upcoming is None and s_utc > now:
                upcoming = _localize(p, shift, tz)
            if current is not None and upcoming is not None:
                break
        out.append(NowNext(channel=channel, timezone=tz_name, current=current, upcoming=upcoming))
    return out


async def highlights(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
    soon_hours: int = 10,
    week_days: int = 7,
    top_n: int = 15,
) -> tuple[list[SearchHit], list[SearchHit]]:
    """``(films_soon, top_rated)`` — films starting within ``soon_hours``, and
    the highest TMDB-rated films across the next ``week_days``. Each list holds
    one entry per film (earliest airing), times in the channel's zone."""
    now = now or _now()
    week_end = now + timedelta(days=week_days)
    # Widened by the max clock-shift; re-filtered to the real window once each
    # film's channel shift is known.
    films = list(
        await session.scalars(
            select(Programme)
            .where(
                Programme.tenant_id == tenant_id,
                Programme.is_movie.is_(True),
                Programme.start_utc >= now - MAX_CLOCK_SHIFT,
                Programme.start_utc <= week_end + MAX_CLOCK_SHIFT,
            )
            .order_by(Programme.start_utc)
        )
    )
    if not films:
        return [], []

    channels = {
        c.id: c
        for c in await session.scalars(
            select(Channel).where(Channel.id.in_({p.channel_id for p in films}))
        )
    }
    sources = {
        s.id: s
        for s in await session.scalars(
            select(Source).where(Source.id.in_({c.source_id for c in channels.values()}))
        )
    }
    tenant = await session.get(Tenant, tenant_id)
    default_tz = tenant.default_timezone if tenant else "UTC"

    def _shift(p: Programme) -> timedelta:
        channel = channels[p.channel_id]
        return timedelta(seconds=_shift_seconds(channel, sources.get(channel.source_id)))

    def hit(p: Programme) -> SearchHit:
        channel = channels[p.channel_id]
        source = sources.get(channel.source_id)
        tz, tz_name = resolve_display_tz(source, default_tz)
        _p, ls, le = _localize(p, _shift(p), tz)
        return SearchHit(
            programme=p, channel=channel, local_start=ls, local_stop=le, timezone=tz_name
        )

    # Keep only films whose *effective* (shift-applied) start is in the window,
    # and order by that effective start.
    films = [p for p in films if now <= p.start_utc + _shift(p) <= week_end]
    if not films:
        return [], []
    films.sort(key=lambda p: p.start_utc + _shift(p))

    soon_end = now + timedelta(hours=soon_hours)
    seen_soon: set[tuple[str, str]] = set()
    films_soon: list[SearchHit] = []
    for p in films:
        if p.start_utc + _shift(p) > soon_end:
            break
        k = cache_key(p.title, p.year)
        if k in seen_soon:
            continue
        seen_soon.add(k)
        films_soon.append(hit(p))

    film_keys = {cache_key(p.title, p.year) for p in films}
    rated = {
        (e.query_key, e.query_year): e.rating
        for e in await session.scalars(
            select(TmdbEnrichment).where(
                TmdbEnrichment.media_type == MediaType.movie,
                TmdbEnrichment.query_key.in_({key for key, _year in film_keys}),
                TmdbEnrichment.rating.is_not(None),
            )
        )
    }
    scored: list[tuple[float, Programme]] = []
    seen_rated: set[tuple[str, str]] = set()
    for p in films:
        k = cache_key(p.title, p.year)
        rating = rated.get(k)
        if rating is None or k in seen_rated:
            continue
        seen_rated.add(k)
        scored.append((rating, p))
    scored.sort(key=lambda t: t[0], reverse=True)
    top_rated = [hit(p) for _r, p in scored[:top_n]]
    return films_soon, top_rated


async def programme_counts(session: AsyncSession, epg_source_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Programme)
            .where(Programme.epg_source_id == epg_source_id)
        )
        or 0
    )
