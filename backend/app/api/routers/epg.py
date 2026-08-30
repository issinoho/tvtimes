"""EPG sources and channel schedules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.auth.deps import SessionDep, VerifiedUser
from app.models.epg import EpgSource
from app.models.source import Channel
from app.queue import enqueue_epg_refresh
from app.schemas.auth import MessageOut
from app.schemas.epg import EpgSourceIn, EpgSourceOut, ProgrammeOut, ScheduleOut
from app.services import epg as svc

router = APIRouter(tags=["epg"])


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

    now = datetime.now(UTC)
    start = frm or now - timedelta(hours=1)
    end = to or start + timedelta(hours=12)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start or end - start > timedelta(days=14):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bad time range")

    triples, tz_name = await svc.channel_schedule(session, channel, start=start, end=end)
    return ScheduleOut(
        channel_id=channel.id,
        channel_name=channel.name,
        timezone=tz_name,
        programmes=[
            ProgrammeOut(
                id=p.id,
                start=ls,
                stop=le,
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
            for (p, ls, le) in triples
        ],
    )
