"""Source management: CRUD, manual refresh, channel listing."""

from __future__ import annotations

import uuid
import zoneinfo
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.auth.deps import SessionDep, VerifiedUser
from app.ingest.redact import source_config_summary
from app.models.source import Source, SourceKind
from app.queue import enqueue_source_refresh
from app.schemas.auth import MessageOut
from app.schemas.source import (
    ChannelOut,
    ChannelPage,
    SourceIn,
    SourceOrderIn,
    SourceOut,
    SourcePatchIn,
)
from app.services import sources as svc

router = APIRouter(prefix="/sources", tags=["sources"])


def _to_out(source: Source, health: svc.SourceHealth) -> SourceOut:
    out = SourceOut.model_validate(source)
    out.config_summary = source_config_summary(source.kind.value, svc.decrypt_config(source))
    out.health = health.health
    out.epg_status = health.epg_status
    out.epg_error = health.epg_error
    out.epg_last_fetched_at = health.epg_last_fetched_at
    out.programme_count = health.programme_count
    return out


async def _one_out(session: SessionDep, source: Source) -> SourceOut:
    health = (await svc.health_by_source(session, [source]))[source.id]
    return _to_out(source, health)


def _check_timezone(name: str | None) -> None:
    if name is None:
        return
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown timezone") from exc


@router.get("", response_model=list[SourceOut])
async def list_sources(user: VerifiedUser, session: SessionDep) -> list[SourceOut]:
    rows = await svc.list_sources(session, user.tenant_id)
    health = await svc.health_by_source(session, rows)
    return [_to_out(s, health[s.id]) for s in rows]


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceIn, user: VerifiedUser, session: SessionDep) -> SourceOut:
    _check_timezone(body.timezone_override)
    source = await svc.create_source(
        session,
        tenant_id=user.tenant_id,
        kind=SourceKind(body.kind),
        display_name=body.display_name,
        config=body.config_dict(),
        timezone_override=body.timezone_override,
        clock_shift_seconds=body.clock_shift_seconds,
        refresh_interval_minutes=body.refresh_interval_minutes,
    )
    await session.flush()
    await enqueue_source_refresh(source.id)
    return await _one_out(session, source)


@router.put("/order", response_model=list[SourceOut])
async def reorder_sources(
    body: SourceOrderIn, user: VerifiedUser, session: SessionDep
) -> list[SourceOut]:
    try:
        await svc.reorder_sources(session, user.tenant_id, body.ids)
    except svc.SourceNotFound as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The id list must be exactly your current sources.",
        ) from exc
    await session.flush()
    rows = await svc.list_sources(session, user.tenant_id)
    health = await svc.health_by_source(session, rows)
    return [_to_out(s, health[s.id]) for s in rows]


async def _load(session: SessionDep, user: VerifiedUser, source_id: uuid.UUID) -> Source:
    try:
        return await svc.get_source(session, user.tenant_id, source_id)
    except svc.SourceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown source") from exc


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: uuid.UUID, user: VerifiedUser, session: SessionDep) -> SourceOut:
    return await _one_out(session, await _load(session, user, source_id))


@router.patch("/{source_id}", response_model=SourceOut)
async def patch_source(
    source_id: uuid.UUID, body: SourcePatchIn, user: VerifiedUser, session: SessionDep
) -> SourceOut:
    source = await _load(session, user, source_id)
    _check_timezone(body.timezone_override)
    fields = body.model_dump(exclude_unset=True)
    await svc.update_source(
        session,
        source,
        display_name=fields.get("display_name"),
        enabled=fields.get("enabled"),
        timezone_override=fields.get("timezone_override"),
        unset_timezone="timezone_override" in fields and fields["timezone_override"] is None,
        clock_shift_seconds=fields.get("clock_shift_seconds"),
        refresh_interval_minutes=fields.get("refresh_interval_minutes"),
    )
    await session.flush()
    return await _one_out(session, source)


@router.delete("/{source_id}", response_model=MessageOut)
async def delete_source(
    source_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    source = await _load(session, user, source_id)
    await svc.delete_source(session, source)
    return MessageOut(message="Source removed.")


@router.post(
    "/{source_id}/refresh", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED
)
async def refresh_source(
    source_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    source = await _load(session, user, source_id)
    await enqueue_source_refresh(source.id, force_epg=True)
    return MessageOut(message="Refresh queued.")


@router.get("/{source_id}/channels", response_model=ChannelPage)
async def list_channels(
    source_id: uuid.UUID,
    user: VerifiedUser,
    session: SessionDep,
    group: Annotated[str | None, Query(max_length=400)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChannelPage:
    source = await _load(session, user, source_id)
    rows, total = await svc.list_channels(
        session, source, group=group, search=search, limit=limit, offset=offset
    )
    counts = await svc.programme_counts(session, [c.id for c in rows])
    return ChannelPage(
        items=[
            ChannelOut.model_validate(c).model_copy(update={"programme_count": counts.get(c.id, 0)})
            for c in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
