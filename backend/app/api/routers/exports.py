"""M3U playlist + XMLTV guide export for external players, and per-channel
stream resolution. Auth is the per-tenant export token as ``?token=`` — a tuner
client can't send a bearer header."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse

from app.auth import tokens
from app.auth.deps import SessionDep
from app.auth.ratelimit import limiter
from app.config import get_settings
from app.models.source import Channel, Source
from app.models.tenant import Tenant
from app.services import exports as svc

router = APIRouter(prefix="/exports", tags=["exports"])

EXPORT_LIMIT = "30/minute"


async def _tenant(session: SessionDep, token: Annotated[str, Query()] = "") -> Tenant:
    tenant = await svc.tenant_for_token(session, token)
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing export token")
    return tenant


TenantDep = Annotated[Tenant, Depends(_tenant)]


@router.get("/playlist.m3u", response_class=PlainTextResponse, include_in_schema=False)
@limiter.limit(EXPORT_LIMIT)
async def playlist(
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    token: Annotated[str, Query()] = "",
) -> PlainTextResponse:
    base = get_settings().public_origin.rstrip("/")
    body = await svc.render_m3u(session, tenant, base_url=base, token=token)
    return PlainTextResponse(
        body,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": 'attachment; filename="tvtimes.m3u"'},
    )


@router.get("/epg.xml", include_in_schema=False)
@limiter.limit(EXPORT_LIMIT)
async def epg_xml(request: Request, tenant: TenantDep, session: SessionDep) -> StreamingResponse:
    return StreamingResponse(
        svc.render_xmltv(session, tenant),
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="tvtimes.xml"'},
    )


@router.get("/stream/{channel_id}", include_in_schema=False)
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
)
@limiter.limit(EXPORT_LIMIT)
async def play_playlist(
    request: Request,
    channel: PlayChannelDep,
    ticket: Annotated[str, Query()] = "",
) -> PlainTextResponse:
    base = get_settings().public_origin.rstrip("/")
    stream_url = f"{base}/api/exports/play/{channel.id}/stream?ticket={ticket}"
    return PlainTextResponse(
        svc.render_channel_m3u(channel, stream_url),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{svc.play_m3u_filename(channel)}"'},
    )


@router.get("/play/{channel_id}/stream", include_in_schema=False)
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
