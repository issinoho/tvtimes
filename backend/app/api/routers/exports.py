"""M3U playlist + XMLTV guide export for external players, and per-channel
stream resolution. Auth is the per-tenant export token as ``?token=`` — a tuner
client can't send a bearer header."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import tokens
from app.auth.deps import SessionDep
from app.auth.ratelimit import limiter
from app.config import get_settings
from app.models.source import Channel, Source
from app.models.tenant import Tenant
from app.services import exports as svc
from app.services import watch as watch_svc

router = APIRouter(prefix="/exports", tags=["exports"])

EXPORT_LIMIT = "30/minute"


async def _tenant(session: SessionDep, token: Annotated[str, Query()] = "") -> Tenant:
    tenant = await svc.tenant_for_token(session, token)
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing export token")
    # Every export route depends on this, so one call here covers the lot --
    # the playlist, the guide, watchlist/favourites polling, a stream request
    # and a watch-state report all count as the token being used.
    await svc.touch_export_token(session, tenant)
    return tenant


TenantDep = Annotated[Tenant, Depends(_tenant)]


@router.get(
    "/playlist.m3u",
    response_class=PlainTextResponse,
    include_in_schema=False,
    summary="The whole line-up as an M3U playlist",
    responses={
        200: {
            "description": "M3U playlist. Channels are keyed by tvtimes' own channel UUID in "
            "both this file and the guide, so a player links a programme to its channel 1:1 "
            "even when several upstream channels share a tvg-id.",
            "content": {"application/x-mpegurl": {"schema": {"type": "string"}}},
        },
        401: {"description": "Invalid or missing export token"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def playlist(
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    token: Annotated[str, Query()] = "",
) -> PlainTextResponse:
    """Every channel of every enabled source, de-duplicated, in the order the
    Sources screen shows. Each entry's stream URL points back at
    ``/api/exports/stream/{channel_id}`` rather than the upstream provider, so
    provider credentials never leave the server."""
    base = get_settings().public_origin.rstrip("/")
    body = await svc.render_m3u(session, tenant, base_url=base, token=token)
    return PlainTextResponse(
        body,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": 'attachment; filename="tvtimes.m3u"'},
    )


@router.get(
    "/epg.xml",
    include_in_schema=False,
    summary="The guide as XMLTV",
    responses={
        200: {
            "description": "XMLTV guide, streamed. Programme times are written already shifted "
            "into each channel's display zone with the right +ZZZZ offset, so a downstream "
            "guide needs no further correction -- that is the whole point of the export.",
            "content": {"application/xml": {"schema": {"type": "string"}}},
        },
        401: {"description": "Invalid or missing export token"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def epg_xml(request: Request, tenant: TenantDep, session: SessionDep) -> StreamingResponse:
    """The guide for every channel in ``playlist.m3u``, keyed by the same
    channel UUIDs."""
    return StreamingResponse(
        svc.render_xmltv(session, tenant),
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="tvtimes.xml"'},
    )


@router.get(
    "/watchlist.json",
    include_in_schema=False,
    summary="Upcoming watchlisted airings",
    responses={
        200: {
            "description": "Every upcoming airing anyone on the account has watchlisted, with "
            "corrected times and the same stream URLs the playlist uses. The watchlist is per "
            "user while the token is per account, so this is the union across the household, "
            "de-duplicated per broadcast."
        },
        401: {"description": "Invalid or missing export token"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def watchlist_json(
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    token: Annotated[str, Query()] = "",
) -> list[dict[str, object]]:
    """Every upcoming watchlisted airing on this account, flat enough for a
    recorder to act on without understanding tvtimes — see
    ``exports.render_watchlist``. Same per-tenant token as the playlist and
    guide feeds; consumed by tvdinner's ``--record-watchlist``."""
    base = get_settings().public_origin.rstrip("/")
    return await svc.render_watchlist(session, tenant, base_url=base, token=token)


class WatchEventIn(BaseModel):
    """One reported viewing interval. Times are corrected UTC — the reporter
    played the export feed, whose guide is already clock-shifted."""

    channel_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    title: str | None = Field(default=None, max_length=500)
    device: str | None = Field(default=None, max_length=120)


class WatchEventsIn(BaseModel):
    events: list[WatchEventIn] = Field(default_factory=list, max_length=500)


@router.get(
    "/favourites.json",
    include_in_schema=False,
    summary="Favourited channels",
    responses={
        200: {
            "description": "Channels anyone on the account has starred. Carries channel_name "
            "as well as the id, because a consumer may key favourites by display name."
        },
        401: {"description": "Invalid or missing export token"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def favourites_json(
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    token: Annotated[str, Query()] = "",
) -> list[dict[str, object]]:
    """Channels anyone on this account has favourited, so a player can show the
    same stars — see ``exports.render_favourites``. Consumed by tvdinner's
    ``--sync-favourites``."""
    base = get_settings().public_origin.rstrip("/")
    return await svc.render_favourites(session, tenant, base_url=base, token=token)


@router.post(
    "/watch-events",
    include_in_schema=False,
    summary="Report what a player watched",
    responses={
        200: {
            "description": "Counts of what was stored and what was skipped. Skipped rows are "
            "those for channels outside this account, or with an implausible duration -- a bad "
            "row never fails the batch."
        },
        401: {"description": "Invalid or missing export token"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def watch_events(
    request: Request,
    body: WatchEventsIn,
    tenant: TenantDep,
    session: SessionDep,
) -> dict[str, int]:
    """Report what a player actually watched, so the guide can show it back.

    The only *write* the export token permits. Deliberately narrow: it appends
    viewing intervals for channels already in this tenant and nothing else, so
    the worst a leaked token can do here is pollute your own watched badges —
    the same token already exposes the whole line-up and streams through it.

    Idempotent on ``(channel_id, started_at)``, so a reporter may safely resend
    its log or retry a failed batch. Rows for channels outside the tenant, or
    with an implausible duration, are skipped rather than failing the batch.
    """
    stored, skipped = await watch_svc.record_watch_events(
        session,
        tenant.id,
        [
            watch_svc.ReportedWatch(
                channel_id=e.channel_id,
                started_at=e.started_at,
                ended_at=e.ended_at,
                title=e.title,
                device=e.device,
            )
            for e in body.events
        ],
    )
    return {"stored": stored, "skipped": skipped}


@router.get(
    "/stream/{channel_id}",
    include_in_schema=False,
    summary="Resolve one channel to its real stream",
    responses={
        302: {
            "description": "Redirect to the upstream stream URL. Provider credentials "
            "(Xtream logins and the like) stay on the server and never appear in the playlist."
        },
        401: {"description": "Invalid or missing export token"},
        404: {"description": "Unknown channel, or not on this account"},
        501: {
            "description": "This source kind can't be resolved to a stream yet (Stalker portals)"
        },
    },
)
@limiter.limit(EXPORT_LIMIT)
async def stream(
    request: Request,
    channel_id: uuid.UUID,
    tenant: TenantDep,
    session: SessionDep,
) -> RedirectResponse:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.tenant_id != tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown channel")
    source = await session.get(Source, channel.source_id)
    try:
        url = svc.resolve_stream(channel, source)
    except svc.StreamUnavailable as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


# --- "Play externally" hand-off (time-limited per-channel ticket) ------------
# Kept off /stream/{id} so the ?token= (export) and ?ticket= (play) auth schemes
# never mix on one path.


async def _play_channel(
    session: SessionDep,
    channel_id: uuid.UUID,
    ticket: Annotated[str, Query()] = "",
) -> Channel:
    try:
        tok_channel_id, tok_tenant_id = tokens.decode_play_token(ticket)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired play link") from exc
    if tok_channel_id != channel_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired play link")
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.tenant_id != tok_tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown channel")
    return channel


PlayChannelDep = Annotated[Channel, Depends(_play_channel)]


@router.get(
    "/play/{channel_id}/playlist.m3u",
    response_class=PlainTextResponse,
    include_in_schema=False,
    summary="One channel as an M3U, behind a play ticket",
    responses={
        200: {
            "description": "A single-channel M3U whose url-tvg points at this channel's own "
            "guide. Both carry the same ticket, so the link reaches exactly one channel.",
            "content": {"audio/x-mpegurl": {"schema": {"type": "string"}}},
        },
        401: {"description": "Invalid or expired play link"},
        404: {"description": "Unknown channel"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def play_playlist(
    request: Request,
    channel: PlayChannelDep,
    ticket: Annotated[str, Query()] = "",
) -> PlainTextResponse:
    """The "Play externally" hand-off: what the web app's **Play** button emits.
    Authenticated by a 24-hour per-channel ticket rather than the export token,
    so handing someone a programme doesn't hand them the whole account."""
    root = f"{get_settings().public_origin.rstrip('/')}/api/exports/play/{channel.id}"
    return PlainTextResponse(
        svc.render_channel_m3u(
            channel,
            f"{root}/stream?ticket={ticket}",
            epg_url=f"{root}/epg.xml?ticket={ticket}",
        ),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{svc.play_m3u_filename(channel)}"'},
    )


@router.get(
    "/play/{channel_id}/epg.xml",
    include_in_schema=False,
    summary="One channel's guide, behind a play ticket",
    responses={
        200: {
            "description": "XMLTV for this channel alone.",
            "content": {"application/xml": {"schema": {"type": "string"}}},
        },
        401: {"description": "Invalid or expired play link"},
        404: {"description": "Unknown channel"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def play_epg_xml(
    request: Request,
    channel: PlayChannelDep,
    session: SessionDep,
) -> StreamingResponse:
    """One channel's XMLTV — what the hand-off `.m3u`'s ``url-tvg=`` points at.
    Same play ticket, so it reaches exactly the one channel and nothing else."""
    tenant = await session.get(Tenant, channel.tenant_id)
    default_tz = (tenant.default_timezone if tenant else None) or "UTC"
    filename = svc.play_m3u_filename(channel).removesuffix(".m3u") + ".xml"
    return StreamingResponse(
        svc.render_channel_xmltv(session, channel, default_tz=default_tz),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/play/{channel_id}/stream",
    include_in_schema=False,
    summary="Resolve one channel, behind a play ticket",
    responses={
        302: {"description": "Redirect to the upstream stream URL."},
        401: {"description": "Invalid or expired play link"},
        404: {"description": "Unknown channel"},
        501: {"description": "This source kind can't be resolved to a stream yet"},
    },
)
@limiter.limit(EXPORT_LIMIT)
async def play_stream(
    request: Request,
    channel: PlayChannelDep,
    session: SessionDep,
) -> RedirectResponse:
    source = await session.get(Source, channel.source_id)
    try:
        url = svc.resolve_stream(channel, source)
    except svc.StreamUnavailable as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
