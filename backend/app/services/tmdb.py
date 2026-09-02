"""TMDB token management, the enrichment cache, and hero assembly."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt, encrypt
from app.ingest import tmdb as client
from app.ingest.tmdb import TmdbError
from app.ingest.xmltv import normalize_name
from app.logging import get_logger
from app.models.epg import Programme
from app.models.source import Channel
from app.models.tenant import Tenant
from app.models.tmdb import MediaType, TmdbEnrichment

_log = get_logger("services.tmdb")

CACHE_TTL = timedelta(days=30)
_WINDOW_FUTURE = timedelta(days=7)
_MAX_PER_REFRESH = 250

# Gentle client-side pacing (TMDB tolerates ~50/s; one worker, be nice).
_MIN_INTERVAL = 0.06
_last_call = 0.0
_pace_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


# --- token ---------------------------------------------------------------------


async def set_token(session: AsyncSession, tenant_id: uuid.UUID, raw_token: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("unknown tenant")
    tenant.tmdb_token_encrypted = encrypt(raw_token.strip())


async def clear_token(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is not None:
        tenant.tmdb_token_encrypted = None


async def token_for(session: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or not tenant.tmdb_token_encrypted:
        return None
    try:
        return decrypt(tenant.tmdb_token_encrypted)
    except ValueError:  # pragma: no cover - key rotation
        return None


async def token_looks_valid(raw_token: str) -> bool:
    """A cheap /authentication ping so the Settings UI can confirm the key."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            resp = await c.get(
                "https://api.themoviedb.org/3/authentication",
                headers={"Authorization": f"Bearer {raw_token.strip()}"},
            )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


# --- enrichment cache --------------------------------------------------------


async def _paced() -> None:
    global _last_call
    async with _pace_lock:
        loop = asyncio.get_running_loop()
        wait = _MIN_INTERVAL - (loop.time() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = loop.time()


def cache_key(title: str, year: str | None) -> tuple[str, str]:
    """The (query_key, query_year) a programme maps to in ``tmdb_enrichment``.
    Shared with ``services.epg`` so the guide highlights join on the same key.

    Falls back to a year embedded in the title itself (e.g. "The Longest
    Yard (1974)") when the source's own ``<date>`` is missing — see
    ``app.ingest.tmdb.guess_trailing_year``. ``client.search`` applies the
    same fallback, so the two stay in step."""
    if not year:
        title, year = client.guess_trailing_year(title)
    return normalize_name(title)[:300], (year or "")


async def _lookup(
    session: AsyncSession, media: MediaType, key: str, year_key: str
) -> TmdbEnrichment | None:
    row: TmdbEnrichment | None = await session.scalar(
        select(TmdbEnrichment).where(
            TmdbEnrichment.media_type == media,
            TmdbEnrichment.query_key == key,
            TmdbEnrichment.query_year == year_key,
        )
    )
    return row


async def enrich_one(
    session: AsyncSession,
    *,
    media_type: MediaType,
    title: str,
    year: str | None,
    token: str,
    http: httpx.AsyncClient,
    force: bool = False,
) -> TmdbEnrichment | None:
    """Return a fresh cache row for ``title``, fetching from TMDB on a miss.
    Returns None only on a hard request failure (never cached)."""
    key, year_key = cache_key(title, year)
    row = await _lookup(session, media_type, key, year_key)
    if row is not None and not force and _now() - row.fetched_at < CACHE_TTL:
        return row

    try:
        await _paced()
        result = await client.search(http, media_type.value, title, year, token)
        detail = (
            await client.details(http, media_type.value, int(result["id"]), token)
            if result
            else None
        )
    except TmdbError as exc:
        _log.warning("tmdb.fetch_failed", title=title, error=str(exc))
        return None

    if row is None:
        row = TmdbEnrichment(media_type=media_type, query_key=key, query_year=year_key)
        session.add(row)
    row.fetched_at = _now()

    if result is None or detail is None:
        row.negative = True
        row.tmdb_id = None
        return row

    e = client.build_enrichment(media_type.value, result, detail)
    row.negative = False
    row.tmdb_id = e.tmdb_id
    row.title = e.title
    row.release_year = e.release_year
    row.overview = e.overview
    row.tagline = e.tagline
    row.rating = e.rating
    row.runtime = e.runtime
    row.director = e.director
    row.genres = e.genres
    row.cast = list(e.cast)
    row.backdrop_url = e.backdrop_url
    row.poster_url = e.poster_url
    row.logo_url = e.logo_url
    return row


# --- background window pass -------------------------------------------------


async def enrich_epg_window(session: AsyncSession, tenant_id: uuid.UUID, token: str) -> int:
    """Warm the cache for distinct titles airing in the next week."""
    now = _now()
    rows = await session.scalars(
        select(Programme)
        .where(
            Programme.tenant_id == tenant_id,
            Programme.start_utc >= now - timedelta(hours=6),
            Programme.start_utc <= now + _WINDOW_FUTURE,
        )
        .order_by(Programme.start_utc)
    )
    seen: set[tuple[str, str, str]] = set()
    done = 0
    async with httpx.AsyncClient() as http:
        for p in rows:
            media = MediaType.movie if p.is_movie else MediaType.tv
            key, year_key = cache_key(p.title, p.year)
            sig = (media.value, key, year_key)
            if not key or sig in seen:
                continue
            seen.add(sig)
            await enrich_one(
                session,
                media_type=media,
                title=p.title,
                year=p.year,
                token=token,
                http=http,
            )
            done += 1
            if done >= _MAX_PER_REFRESH:
                break
            if done % 25 == 0:
                await session.flush()
    _log.info("tmdb.window_enriched", tenant_id=str(tenant_id), titles=done)
    return done


# --- hero --------------------------------------------------------------------


async def art_for(session: AsyncSession, programme: Programme) -> str | None:
    """A poster (else backdrop) URL for ``programme`` from the enrichment cache,
    or None if it was never enriched or matched nothing. Always a stable
    ``https://image.tmdb.org`` URL — safe to hand to a notifier as an
    attachment. No freshness check (a slightly stale image URL is fine) and it
    never triggers a fetch."""
    media = MediaType.movie if programme.is_movie else MediaType.tv
    key, year_key = cache_key(programme.title, programme.year)
    row = await _lookup(session, media, key, year_key)
    if row is None or row.negative:
        return None
    return row.poster_url or row.backdrop_url


@dataclass(slots=True)
class Hero:
    programme: Programme
    channel: Channel
    enrichment: TmdbEnrichment | None
    tmdb_connected: bool
    enriching: bool


async def hero_for(
    session: AsyncSession, tenant_id: uuid.UUID, programme_id: uuid.UUID
) -> Hero | None:
    programme = await session.get(Programme, programme_id)
    if programme is None or programme.tenant_id != tenant_id:
        return None
    channel = await session.get(Channel, programme.channel_id)
    if channel is None:
        return None

    token = await token_for(session, tenant_id)
    media = MediaType.movie if programme.is_movie else MediaType.tv
    key, year_key = cache_key(programme.title, programme.year)
    row = await _lookup(session, media, key, year_key)
    fresh = row is not None and _now() - row.fetched_at < CACHE_TTL
    return Hero(
        programme=programme,
        channel=channel,
        enrichment=row if fresh else None,
        tmdb_connected=token is not None,
        enriching=token is not None and not fresh,
    )


async def enrich_programme(
    session: AsyncSession, tenant_id: uuid.UUID, programme_id: uuid.UUID
) -> None:
    """On-demand single enrichment (queued when a hero is opened cold)."""
    programme = await session.get(Programme, programme_id)
    if programme is None or programme.tenant_id != tenant_id:
        return
    token = await token_for(session, tenant_id)
    if token is None:
        return
    media = MediaType.movie if programme.is_movie else MediaType.tv
    async with httpx.AsyncClient() as http:
        await enrich_one(
            session,
            media_type=media,
            title=programme.title,
            year=programme.year,
            token=token,
            http=http,
        )
