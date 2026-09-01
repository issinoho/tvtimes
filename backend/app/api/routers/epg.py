"""EPG sources and channel schedules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.auth import tokens
from app.auth.deps import SessionDep, VerifiedUser
from app.auth.ratelimit import limiter
from app.config import get_settings
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source
from app.queue import enqueue_epg_refresh
from app.schemas.auth import MessageOut
from app.schemas.epg import (
    ChannelPatchIn,
    ChannelShiftOut,
    EpgSourceIn,
    EpgSourceOut,
    GuideChannelOut,
    GuideOut,
    HighlightsOut,
    NowNextOut,
    NowNextRowOut,
    PlayLinkOut,
    ProgrammeOut,
    ScheduleOut,
    SearchChannelOut,
    SearchHitOut,
    SearchOut,
)
from app.services import epg as svc
from app.services import exports as exports_svc
from app.services import logos as logo_svc
from app.services import sources as src_svc

router = APIRouter(tags=["epg"])


def _search_channel_out(channel: Channel, timezone: str) -> SearchChannelOut:
    return SearchChannelOut(
        id=channel.id,
        name=channel.name,
        number=channel.number,
        logo_url=channel.logo_url,
        group_title=channel.group_title,
        is_hd=channel.is_hd,
        timezone=timezone,
        clock_shift_seconds=channel.clock_shift_seconds,
    )


def _hit_out(h: svc.SearchHit) -> SearchHitOut:
    return SearchHitOut(
        channel=_search_channel_out(h.channel, h.timezone),
        programme=_programme_out(h.programme, h.local_start, h.local_stop),
    )


def _programme_out(p: Programme, local_start: datetime, local_stop: datetime) -> ProgrammeOut:
    return ProgrammeOut(
        id=p.id,
        start=local_start,
        stop=local_stop,
        title=p.title,
        sub_title=p.sub_title,
        description=p.description,
        categories=p.categories,
        episode_num=p.episode_num,
        year=p.year,
        icon_url=p.icon_url,
        director=p.director,
        is_movie=p.is_movie,
    )


def _clamp_range(
    frm: datetime | None, to: datetime | None, *, default_span: timedelta, max_span: timedelta
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = frm or now - timedelta(hours=1)
    end = to or start + default_span
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start or end - start > max_span:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bad time range")
    return start, end


@router.get("/epg-sources", response_model=list[EpgSourceOut])
async def list_epg_sources(user: VerifiedUser, session: SessionDep) -> list[EpgSourceOut]:
    rows = await svc.list_epg_sources(session, user.tenant_id)
    return [EpgSourceOut.model_validate(r) for r in rows]


@router.post("/epg-sources", response_model=EpgSourceOut, status_code=status.HTTP_201_CREATED)
async def create_epg_source(
    body: EpgSourceIn, user: VerifiedUser, session: SessionDep
) -> EpgSourceOut:
    row = await svc.create_epg_source(session, tenant_id=user.tenant_id, url=body.url)
    await session.flush()
    await enqueue_epg_refresh(row.id)
    return EpgSourceOut.model_validate(row)


async def _load(session: SessionDep, user: VerifiedUser, epg_source_id: uuid.UUID) -> EpgSource:
    try:
        return await svc.get_epg_source(session, user.tenant_id, epg_source_id)
    except svc.EpgSourceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown EPG source") from exc


@router.post(
    "/epg-sources/{epg_source_id}/refresh",
    response_model=MessageOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_epg_source(
    epg_source_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    row = await _load(session, user, epg_source_id)
    await enqueue_epg_refresh(row.id)
    return MessageOut(message="EPG refresh queued.")


@router.delete("/epg-sources/{epg_source_id}", response_model=MessageOut)
async def delete_epg_source(
    epg_source_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    row = await _load(session, user, epg_source_id)
    if row.source_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This EPG is managed by its source. Remove or edit the source instead.",
        )
    await svc.delete_epg_source(session, row)
    return MessageOut(message="EPG source removed.")


@router.patch("/channels/{channel_id}", response_model=ChannelShiftOut)
async def patch_channel(
    channel_id: uuid.UUID, body: ChannelPatchIn, user: VerifiedUser, session: SessionDep
) -> ChannelShiftOut:
    try:
        channel = await src_svc.get_channel(session, user.tenant_id, channel_id)
    except src_svc.SourceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown channel") from exc
    await src_svc.set_channel_clock_shift(
        session, channel, clock_shift_seconds=body.clock_shift_seconds
    )
    await session.flush()
    return ChannelShiftOut(id=channel.id, clock_shift_seconds=channel.clock_shift_seconds)


@router.post("/channels/{channel_id}/play-link", response_model=PlayLinkOut)
@limiter.limit("30/minute")
async def create_play_link(
    request: Request, channel_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> PlayLinkOut:
    """Mint a short-lived link the browser hands to the OS so the default media
    player opens this channel. The ticket is scoped to this one channel and
    expires quickly, so it's safe to leave in a downloaded ``.m3u`` or the URL
    bar — unlike the tenant-wide export token."""
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown channel")
    source = await session.get(Source, channel.source_id)
    try:
        exports_svc.resolve_stream(channel, source)  # pre-flight; body value unused
    except exports_svc.StreamUnavailable as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc

    ticket = tokens.issue_play_token(channel.id, user.tenant_id)
    root = f"{get_settings().public_origin.rstrip('/')}/api/exports/play/{channel.id}"
    return PlayLinkOut(
        m3u_url=f"{root}/playlist.m3u?ticket={ticket}",
        stream_url=f"{root}/stream?ticket={ticket}",
        expires_in=int(tokens.PLAY_TOKEN_TTL.total_seconds()),
    )


@router.get("/channels/{channel_id}/logo", include_in_schema=False)
async def channel_logo(channel_id: uuid.UUID, session: SessionDep) -> Response:
    """Proxy a channel's logo through this origin so an ``http://`` LAN logo URL
    still loads on an HTTPS deployment. Unauthenticated on purpose — it's just an
    icon, keyed by an unguessable UUID, and ``<img>`` can't send a bearer token."""
    channel = await session.get(Channel, channel_id)
    if channel is None or not channel.logo_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    got = await logo_svc.fetch_logo(channel.logo_url)
    if got is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    body, content_type = got
    return Response(
        body,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/channels/{channel_id}/schedule", response_model=ScheduleOut)
async def channel_schedule(
    channel_id: uuid.UUID,
    user: VerifiedUser,
    session: SessionDep,
    frm: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> ScheduleOut:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown channel")

    start, end = _clamp_range(
        frm, to, default_span=timedelta(hours=12), max_span=timedelta(days=14)
    )
    triples, tz_name = await svc.channel_schedule(session, channel, start=start, end=end)
    return ScheduleOut(
        channel_id=channel.id,
        channel_name=channel.name,
        timezone=tz_name,
        programmes=[_programme_out(*t) for t in triples],
    )


@router.get("/guide", response_model=GuideOut)
async def guide(
    user: VerifiedUser,
    session: SessionDep,
    frm: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    group: Annotated[str | None, Query(max_length=400)] = None,
    channels: Annotated[list[uuid.UUID] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=3000)] = 800,
) -> GuideOut:
    start, end = _clamp_range(
        frm, to, default_span=timedelta(hours=6), max_span=timedelta(hours=36)
    )
    rows = await svc.guide(
        session,
        user.tenant_id,
        start=start,
        end=end,
        source_id=source_id,
        group=group,
        channel_ids=channels,
        limit=limit,
    )
    return GuideOut(
        from_=start,
        to=end,
        channels=[
            GuideChannelOut(
                id=r.channel.id,
                name=r.channel.name,
                number=r.channel.number,
                logo_url=r.channel.logo_url,
                group_title=r.channel.group_title,
                is_hd=r.channel.is_hd,
                timezone=r.timezone,
                clock_shift_seconds=r.channel.clock_shift_seconds,
                programmes=[_programme_out(*t) for t in r.programmes],
            )
            for r in rows
        ],
    )


@router.get("/guide/search", response_model=SearchOut)
async def search_guide(
    user: VerifiedUser,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    movies_only: Annotated[bool, Query()] = False,
    frm: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 100,
) -> SearchOut:
    # Default to the next week; allow anywhere in the stored window.
    start, end = _clamp_range(frm, to, default_span=timedelta(days=7), max_span=timedelta(days=16))
    hits = await svc.search_programmes(
        session,
        user.tenant_id,
        query=q,
        movies_only=movies_only,
        start=start,
        end=end,
        limit=limit,
    )
    return SearchOut(query=q, from_=start, to=end, results=[_hit_out(h) for h in hits])


@router.get("/guide/now-next", response_model=NowNextOut)
async def guide_now_next(
    user: VerifiedUser,
    session: SessionDep,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    group: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> NowNextOut:
    now = datetime.now(UTC)
    rows = await svc.now_next(
        session, user.tenant_id, source_id=source_id, group=group, limit=limit, now=now
    )
    return NowNextOut(
        now=now,
        channels=[
            NowNextRowOut(
                channel=_search_channel_out(r.channel, r.timezone),
                current=_programme_out(*r.current) if r.current else None,
                upcoming=_programme_out(*r.upcoming) if r.upcoming else None,
            )
            for r in rows
        ],
    )


@router.get("/guide/highlights", response_model=HighlightsOut)
async def guide_highlights(user: VerifiedUser, session: SessionDep) -> HighlightsOut:
    films_soon, top_rated = await svc.highlights(session, user.tenant_id)
    return HighlightsOut(
        films_soon=[_hit_out(h) for h in films_soon],
        top_rated=[_hit_out(h) for h in top_rated],
    )
