"""Source CRUD and refresh (fetch → parse → replace channels)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt, encrypt
from app.ingest import channel_logos, hdhomerun, m3u, stalker, xtream
from app.ingest.errors import SourceError, SourceRejected, SourceUnreachable
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from app.ingest.ssrf import assert_allowed_url
from app.logging import get_logger
from app.models.source import Channel, Source, SourceKind, SourceStatus

_CONFIG_URL_FIELD = {
    SourceKind.m3u: "url",
    SourceKind.xtream: "server_url",
    SourceKind.stalker: "portal_url",
}

_log = get_logger("services.sources")


class SourceNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_config(kind: SourceKind, config: dict[str, object]) -> dict[str, object]:
    """Trim/normalise a validated config dict before it is encrypted."""
    if kind is SourceKind.m3u:
        return {"url": str(config["url"]).strip()}
    if kind is SourceKind.xtream:
        return {
            "server_url": str(config["server_url"]).strip().rstrip("/"),
            "username": str(config["username"]),
            "password": str(config["password"]),
            "output": str(config.get("output") or "ts"),
        }
    if kind is SourceKind.stalker:
        return {
            "portal_url": str(config["portal_url"]).strip(),
            "mac": str(config["mac"]).strip().upper(),
            "serial": (str(config["serial"]).strip() or None) if config.get("serial") else None,
            "device_id": (
                (str(config["device_id"]).strip() or None) if config.get("device_id") else None
            ),
            "stb_type": str(config.get("stb_type") or "MAG250"),
        }
    if kind is SourceKind.hdhomerun:
        return {"device_url": str(config.get("device_url") or "").strip().rstrip("/")}
    raise ValueError(f"unknown source kind {kind!r}")


def decrypt_config(source: Source) -> dict[str, object]:
    return json.loads(decrypt(source.config_encrypted))  # type: ignore[no-any-return]


async def assert_config_url_allowed(kind: SourceKind, config: dict[str, object]) -> None:
    """Reject a private/loopback/bad-scheme URL up front. A transient DNS
    failure is left for the refresh to report."""
    field = _CONFIG_URL_FIELD.get(kind)
    if field is None:
        # hdhomerun: the device URL is meant to be a LAN address; it gets its
        # own private-address check at ingest time, not the public-only guard.
        return
    url = str(config[field])
    try:
        await assert_allowed_url(url)
    except SourceRejected:
        raise
    except SourceUnreachable:
        pass


async def create_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: SourceKind,
    display_name: str,
    config: dict[str, object],
    timezone_override: str | None = None,
    clock_shift_seconds: int = 0,
    refresh_interval_minutes: int = 360,
) -> Source:
    normalized = _normalize_config(kind, config)
    await assert_config_url_allowed(kind, normalized)
    max_rank = await session.scalar(
        select(func.max(Source.sort_rank)).where(Source.tenant_id == tenant_id)
    )
    source = Source(
        tenant_id=tenant_id,
        kind=kind,
        display_name=display_name.strip(),
        config_encrypted=encrypt(json.dumps(normalized)),
        timezone_override=timezone_override,
        clock_shift_seconds=clock_shift_seconds,
        refresh_interval_minutes=refresh_interval_minutes,
        sort_rank=(max_rank + 1) if max_rank is not None else 0,
        last_status=SourceStatus.pending,
    )
    session.add(source)
    await session.flush()
    return source


async def list_sources(session: AsyncSession, tenant_id: uuid.UUID) -> Sequence[Source]:
    rows = await session.scalars(
        select(Source)
        .where(Source.tenant_id == tenant_id)
        .order_by(Source.sort_rank, Source.created_at)
    )
    return list(rows)


async def reorder_sources(
    session: AsyncSession, tenant_id: uuid.UUID, ordered_ids: Sequence[uuid.UUID]
) -> None:
    """Set ``sort_rank`` from the given order. ``ordered_ids`` must be exactly
    the tenant's current source ids."""
    rows = {
        s.id: s for s in await session.scalars(select(Source).where(Source.tenant_id == tenant_id))
    }
    if set(ordered_ids) != set(rows) or len(ordered_ids) != len(rows):
        raise SourceNotFound
    for rank, sid in enumerate(ordered_ids):
        rows[sid].sort_rank = rank


async def get_source(session: AsyncSession, tenant_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = await session.get(Source, source_id)
    if source is None or source.tenant_id != tenant_id:
        raise SourceNotFound
    return source


async def update_source(
    session: AsyncSession,
    source: Source,
    *,
    display_name: str | None = None,
    enabled: bool | None = None,
    timezone_override: str | None = None,
    unset_timezone: bool = False,
    clock_shift_seconds: int | None = None,
    refresh_interval_minutes: int | None = None,
    config: dict[str, object] | None = None,
) -> None:
    if display_name is not None:
        source.display_name = display_name.strip()
    if enabled is not None:
        source.enabled = enabled
    if unset_timezone:
        source.timezone_override = None
    elif timezone_override is not None:
        source.timezone_override = timezone_override
    if clock_shift_seconds is not None:
        source.clock_shift_seconds = clock_shift_seconds
    if refresh_interval_minutes is not None:
        source.refresh_interval_minutes = refresh_interval_minutes
    if config is not None:
        normalized = _normalize_config(source.kind, config)
        await assert_config_url_allowed(source.kind, normalized)
        source.config_encrypted = encrypt(json.dumps(normalized))
        source.last_status = SourceStatus.pending


async def delete_source(session: AsyncSession, source: Source) -> None:
    await session.delete(source)


async def get_channel(
    session: AsyncSession, tenant_id: uuid.UUID, channel_id: uuid.UUID
) -> Channel:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.tenant_id != tenant_id:
        raise SourceNotFound
    return channel


async def set_channel_clock_shift(
    session: AsyncSession, channel: Channel, *, clock_shift_seconds: int
) -> None:
    channel.clock_shift_seconds = clock_shift_seconds


# --- refresh ---------------------------------------------------------------


async def _ingest(kind: SourceKind, config: dict[str, object]) -> Playlist:
    if kind is SourceKind.m3u:
        return await m3u.load_m3u_playlist(str(config["url"]))
    if kind is SourceKind.xtream:
        return await xtream.load_xtream_playlist(xtream.XtreamCreds.from_config(config))
    if kind is SourceKind.stalker:
        return await stalker.load_stalker_playlist(stalker.StalkerCreds.from_config(config))
    if kind is SourceKind.hdhomerun:
        return await hdhomerun.load_hdhomerun_playlist(config)
    raise ValueError(f"unknown source kind {kind!r}")


def _dedupe_key(ch: ParsedChannel) -> str:
    """Identity for collapsing repeated playlist lines. Two entries collapse
    only when their tvg-id, name *and* stream target all match, so East/West or
    SD/HD variants — which often share a tvg-id and sometimes even a name — are
    all kept as separate channels. EPG matching still keys on the shared
    tvg-id / name, so both variants still get programmes."""
    digest = hashlib.sha1((ch.stream_ref or "").encode("utf-8"), usedforsecurity=False)
    parts = [(ch.tvg_id or "").strip().lower(), ch.name.strip().lower(), digest.hexdigest()[:12]]
    return "|".join(p for p in parts if p)[:400] or "channel"


async def refresh_source(session: AsyncSession, source: Source) -> bool:
    """Fetch the source and reconcile its channel set **in place** — channels
    are matched to existing rows by ``dedupe_key``, so an unchanged channel
    keeps its id (and its linked programmes survive). Never raises: failures
    land in ``last_status`` / ``last_error``.

    Returns ``True`` when the set of channels changed (a key was added or
    removed); the caller should then force a full EPG rebuild, because the
    new/renumbered channels have no programmes yet.
    """
    try:
        playlist = await _ingest(source.kind, decrypt_config(source))
    except SourceError as exc:
        source.last_status = SourceStatus.error
        source.last_error = exc.message
        source.last_refreshed_at = _now()
        _log.warning("source.refresh_failed", source_id=str(source.id), error=exc.message)
        return False
    except Exception:
        source.last_status = SourceStatus.error
        source.last_error = "An unexpected error occurred while reading this source."
        source.last_refreshed_at = _now()
        _log.exception("source.refresh_crashed", source_id=str(source.id))
        return False

    existing = {
        c.dedupe_key: c
        for c in await session.scalars(select(Channel).where(Channel.source_id == source.id))
    }
    logo_index = await channel_logos.load_index()
    seen: set[str] = set()
    for order, ch in enumerate(playlist.channels):
        key = _dedupe_key(ch)
        if key in seen:
            continue
        seen.add(key)
        row = existing.get(key)
        logo = (
            ch.tvg_logo
            or channel_logos.lookup(
                logo_index, ext_id=ch.tvg_id, name=ch.name, tvg_name=ch.tvg_name
            )
            or (row.logo_url if row else None)  # keep a prior backfill if iptv-org is down
        )
        fields: dict[str, object] = {
            "ext_id": ch.tvg_id,
            "name": ch.name[:400],
            "tvg_name": ch.tvg_name,
            "logo_url": logo,
            "group_title": (ch.group_title or None) and ch.group_title[:400],
            "number": ch.number,
            "is_hd": ch.is_hd,
            "sort_order": order,
            "stream_ref_encrypted": encrypt(ch.stream_ref),
            "last_seen_at": _now(),
        }
        if row is None:
            session.add(
                Channel(tenant_id=source.tenant_id, source_id=source.id, dedupe_key=key, **fields)
            )
        else:
            for name, value in fields.items():
                setattr(row, name, value)

    stale = set(existing) - seen
    if stale:
        await session.execute(
            delete(Channel).where(Channel.source_id == source.id, Channel.dedupe_key.in_(stale))
        )
    changed = bool(stale) or bool(seen - set(existing))

    source.channel_count = len(seen)
    source.epg_url = playlist.epg_url
    source.last_status = SourceStatus.ok
    source.last_error = "; ".join(playlist.warnings) if playlist.warnings else None
    source.last_refreshed_at = _now()
    _log.info(
        "source.refreshed",
        source_id=str(source.id),
        channels=len(seen),
        added=len(seen - set(existing)),
        removed=len(stale),
    )
    return changed


async def list_channels(
    session: AsyncSession,
    source: Source,
    *,
    group: str | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[Sequence[Channel], int]:
    stmt = select(Channel).where(Channel.source_id == source.id)
    count_stmt = select(func.count()).select_from(Channel).where(Channel.source_id == source.id)
    if group:
        stmt = stmt.where(Channel.group_title == group)
        count_stmt = count_stmt.where(Channel.group_title == group)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(Channel.name.ilike(like))
        count_stmt = count_stmt.where(Channel.name.ilike(like))
    stmt = stmt.order_by(Channel.sort_order).limit(limit).offset(offset)
    rows = await session.scalars(stmt)
    total = await session.scalar(count_stmt) or 0
    return list(rows), total


async def due_for_refresh(session: AsyncSession) -> list[uuid.UUID]:
    """Ids of enabled, fetch-backed sources whose refresh interval has elapsed.
    Connector sources are pushed, not pulled, so they are excluded."""
    now = _now()
    rows = await session.scalars(
        select(Source).where(Source.enabled.is_(True), Source.kind != SourceKind.connector)
    )
    due: list[uuid.UUID] = []
    for s in rows:
        if (
            s.last_refreshed_at is None
            or s.last_refreshed_at + timedelta(minutes=s.refresh_interval_minutes) < now
        ):
            due.append(s.id)
    return due
