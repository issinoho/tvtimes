"""Merged M3U playlist and XMLTV guide export for external players
(Jellyfin / Plex / Emby / TiviMate / Threadfin …), plus per-channel stream
resolution.

Auth is a per-tenant bearer token passed as ``?token=`` — a tuner/``<img>``
client can't send an ``Authorization`` header. Only the sha256 of the token is
stored; the raw value is shown once on creation.

Channels are keyed by our own channel UUID in *both* files, so a downstream
player links a programme to its channel 1:1 even when several upstream channels
share a tvg-id (the East/West fan-out case).

Programme times are written already shifted into the channel's display zone with
the right ``+ZZZZ`` offset, so a downstream guide needs no further correction —
that is the whole point of the export.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
import zoneinfo
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape, quoteattr

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt
from app.ingest.xtream import XtreamCreds, build_live_url
from app.logging import get_logger
from app.models.epg import Programme
from app.models.source import Channel, Source, SourceKind
from app.models.tenant import Tenant
from app.services.epg import (
    MAX_CLOCK_SHIFT,
    WINDOW_FUTURE,
    WINDOW_PAST,
    _shift_seconds,
    resolve_display_tz,
)
from app.services.sources import decrypt_config

_log = get_logger("services.exports")


class StreamUnavailable(Exception):
    """No static URL can be produced for this channel (e.g. a Stalker portal,
    whose links are short-lived and must be minted per play)."""


# --- token --------------------------------------------------------------------


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def generate_token(session: AsyncSession, tenant: Tenant) -> str:
    """Mint (or rotate) the tenant's export token and return the raw value once."""
    raw = secrets.token_urlsafe(32)
    tenant.export_token_hash = _hash(raw)
    tenant.export_token_set_at = datetime.now(UTC)
    await session.flush()
    return raw


async def revoke_token(session: AsyncSession, tenant: Tenant) -> None:
    tenant.export_token_hash = None
    tenant.export_token_set_at = None
    await session.flush()


async def tenant_for_token(session: AsyncSession, raw: str) -> Tenant | None:
    if not raw:
        return None
    tenant: Tenant | None = await session.scalar(
        select(Tenant).where(Tenant.export_token_hash == _hash(raw))
    )
    return tenant


# --- channel selection ------------------------------------------------------


async def _ordered_channels(session: AsyncSession, tenant_id: uuid.UUID) -> list[Channel]:
    """Every channel of an enabled source, in the Sources-screen order — the
    same ordering the guide grid uses."""
    stmt = (
        select(Channel)
        .join(Source, Channel.source_id == Source.id)
        .where(Channel.tenant_id == tenant_id, Source.enabled.is_(True))
        .order_by(
            Source.sort_rank,
            Channel.number.is_(None),
            Channel.number,
            Channel.sort_order,
            Channel.name,
        )
    )
    return list(await session.scalars(stmt))


async def _sources_by_id(
    session: AsyncSession, channels: Iterable[Channel]
) -> dict[uuid.UUID, Source]:
    ids = {c.source_id for c in channels}
    if not ids:
        return {}
    return {s.id: s for s in await session.scalars(select(Source).where(Source.id.in_(ids)))}


# --- stream resolution ------------------------------------------------------


def resolve_stream(channel: Channel, source: Source | None) -> str:
    """A directly playable URL for one channel, rebuilding credentials on the
    fly for Xtream. Raises :class:`StreamUnavailable` when no static URL exists."""
    kind = source.kind if source else None
    if kind is SourceKind.xtream and source is not None:
        creds = XtreamCreds.from_config(decrypt_config(source))
        return build_live_url(creds, decrypt(channel.stream_ref_encrypted))
    if kind is SourceKind.stalker:
        raise StreamUnavailable("Stalker portal streams can't be exported as a static URL yet.")
    # m3u, hdhomerun, connector: the stored ref is already a playable URL.
    return decrypt(channel.stream_ref_encrypted)


# --- M3U --------------------------------------------------------------------


def _clean(value: str) -> str:
    """Collapse anything that would break a one-line ``#EXTINF``."""
    return value.replace("\r", " ").replace("\n", " ").strip()


def _attr(value: str) -> str:
    return _clean(value).replace('"', "'")


def _extinf(channel: Channel) -> str:
    attrs = [
        ("tvg-id", str(channel.id)),
        ("tvg-name", channel.tvg_name or channel.name),
    ]
    if channel.logo_url:
        attrs.append(("tvg-logo", channel.logo_url))
    if channel.number is not None:
        attrs.append(("tvg-chno", str(channel.number)))
    if channel.group_title:
        attrs.append(("group-title", channel.group_title))
    joined = " ".join(f'{k}="{_attr(v)}"' for k, v in attrs)
    return f"#EXTINF:-1 {joined},{_clean(channel.name)}"


async def render_m3u(session: AsyncSession, tenant: Tenant, *, base_url: str, token: str) -> str:
    channels = await _ordered_channels(session, tenant.id)
    epg_url = f"{base_url}/api/exports/epg.xml?token={token}"
    lines = [f'#EXTM3U url-tvg="{epg_url}"', ""]
    for ch in channels:
        lines.append(_extinf(ch))
        lines.append(f"{base_url}/api/exports/stream/{ch.id}?token={token}")
    return "\n".join(lines) + "\n"


# --- XMLTV ----------------------------------------------------------------------


def _xmltv_time(dt: datetime) -> str:
    # dt is timezone-aware in the channel's display zone; %z -> "+0100".
    return dt.strftime("%Y%m%d%H%M%S %z")


def _programme_xml(
    p: Programme, channel_id: uuid.UUID, start: datetime, stop: datetime
) -> Iterator[str]:
    # Element order follows the XMLTV DTD.
    yield (
        f'  <programme start="{_xmltv_time(start)}" stop="{_xmltv_time(stop)}" '
        f"channel={quoteattr(str(channel_id))}>\n"
    )
    yield f"    <title>{escape(p.title)}</title>\n"
    if p.sub_title:
        yield f"    <sub-title>{escape(p.sub_title)}</sub-title>\n"
    if p.description:
        yield f"    <desc>{escape(p.description)}</desc>\n"
    if p.director:
        yield "    <credits>\n"
        yield f"      <director>{escape(p.director)}</director>\n"
        yield "    </credits>\n"
    if p.year:
        yield f"    <date>{escape(p.year)}</date>\n"
    for cat in p.categories:
        yield f"    <category>{escape(cat)}</category>\n"
    if p.episode_num:
        yield f'    <episode-num system="onscreen">{escape(p.episode_num)}</episode-num>\n'
    if p.icon_url:
        yield f"    <icon src={quoteattr(p.icon_url)} />\n"
    yield "  </programme>\n"


async def render_xmltv(session: AsyncSession, tenant: Tenant) -> AsyncIterator[str]:
    channels = await _ordered_channels(session, tenant.id)
    sources = await _sources_by_id(session, channels)
    default_tz = tenant.default_timezone or "UTC"

    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield '<tv generator-info-name="tvtimes">\n'
    for ch in channels:
        yield f"  <channel id={quoteattr(str(ch.id))}>\n"
        yield f"    <display-name>{escape(ch.name)}</display-name>\n"
        if ch.logo_url:
            yield f"    <icon src={quoteattr(ch.logo_url)} />\n"
        yield "  </channel>\n"

    if not channels:
        yield "</tv>\n"
        return

    # (tz, shift) per channel, resolved once.
    meta: dict[uuid.UUID, tuple[zoneinfo.ZoneInfo, timedelta]] = {}
    for ch in channels:
        src = sources.get(ch.source_id)
        tz, _name = resolve_display_tz(src, default_tz)
        meta[ch.id] = (tz, timedelta(seconds=_shift_seconds(ch, src)))

    now = datetime.now(UTC)
    start, end = now - WINDOW_PAST, now + WINDOW_FUTURE
    ids = list(meta)
    # Widen by the max clock-shift; each row is re-tested against [start, end)
    # with its channel's shift applied, so a shifted feed's exported guide
    # matches what the grid draws (see CLAUDE.md: export and grid must agree).
    result = await session.stream_scalars(
        select(Programme)
        .where(
            Programme.channel_id.in_(ids),
            Programme.stop_utc > start - MAX_CLOCK_SHIFT,
            Programme.start_utc < end + MAX_CLOCK_SHIFT,
        )
        .order_by(Programme.channel_id, Programme.start_utc)
    )
    async for p in result:
        tz, shift = meta[p.channel_id]
        s_utc, e_utc = p.start_utc + shift, p.stop_utc + shift
        if e_utc <= start or s_utc >= end:
            continue
        for chunk in _programme_xml(p, p.channel_id, s_utc.astimezone(tz), e_utc.astimezone(tz)):
            yield chunk

    yield "</tv>\n"
