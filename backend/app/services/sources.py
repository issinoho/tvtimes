"""Source CRUD and refresh (fetch → parse → replace channels)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt, encrypt
from app.ingest import hdhomerun, m3u, stalker, xtream
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
    source = Source(
        tenant_id=tenant_id,
        kind=kind,
        display_name=display_name.strip(),
        config_encrypted=encrypt(json.dumps(normalized)),
        timezone_override=timezone_override,
        clock_shift_seconds=clock_shift_seconds,
        refresh_interval_minutes=refresh_interval_minutes,
        last_status=SourceStatus.pending,
    )
    session.add(source)
    await session.flush()
    return source


async def list_sources(session: AsyncSession, tenant_id: uuid.UUID) -> Sequence[Source]:
    rows = await session.scalars(
        select(Source).where(Source.tenant_id == tenant_id).order_by(Source.created_at.desc())
    )
    return list(rows)


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
    """Identity for collapsing repeated playlist entries. Keyed on tvg-id *and*
    name so East/West or SD/HD variants that share a tvg-id are kept as
    separate channels (EPG matching still keys on the shared tvg-id); only a
    genuine duplicate line — same id and same name — is dropped."""
    parts = [(ch.tvg_id or "").strip().lower(), ch.name.strip().lower()]
    return ("|".join(p for p in parts if p) or "channel")[:400]


async def refresh_source(session: AsyncSession, source: Source) -> None:
    """Fetch the source and replace its channel set. Never raises: failures
    land in ``last_status`` / ``last_error``."""
    try:
        playlist = await _ingest(source.kind, decrypt_config(source))
    except SourceError as exc:
        source.last_status = SourceStatus.error
        source.last_error = exc.message
        source.last_refreshed_at = _now()
        _log.warning("source.refresh_failed", source_id=str(source.id), error=exc.message)
        return
    except Exception:
        source.last_status = SourceStatus.error
        source.last_error = "An unexpected error occurred while reading this source."
        source.last_refreshed_at = _now()
        _log.exception("source.refresh_crashed", source_id=str(source.id))
        return

    await session.execute(delete(Channel).where(Channel.source_id == source.id))
    seen: set[str] = set()
    for order, ch in enumerate(playlist.channels):
        key = _dedupe_key(ch)
        if key in seen:
            continue
        seen.add(key)
        session.add(
            Channel(
                tenant_id=source.tenant_id,
                source_id=source.id,
                dedupe_key=key,
                ext_id=ch.tvg_id,
                name=ch.name[:400],
                tvg_name=ch.tvg_name,
                logo_url=ch.tvg_logo,
                group_title=(ch.group_title or None) and ch.group_title[:400],
                number=ch.number,
                is_hd=ch.is_hd,
                sort_order=order,
                stream_ref_encrypted=encrypt(ch.stream_ref),
                last_seen_at=_now(),
            )
        )

    source.channel_count = len(seen)
    source.epg_url = playlist.epg_url
    source.last_status = SourceStatus.ok
    source.last_error = "; ".join(playlist.warnings) if playlist.warnings else None
    source.last_refreshed_at = _now()
    _log.info("source.refreshed", source_id=str(source.id), channels=source.channel_count)


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
