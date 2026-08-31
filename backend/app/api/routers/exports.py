"""M3U playlist + XMLTV guide export for external players, and per-channel
stream resolution. Auth is the per-tenant export token as ``?token=`` — a tuner
client can't send a bearer header."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse

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
