"""Per-user watchlist: saved airings and tracked titles. The reminder worker
emails before a matching airing starts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import SessionDep, VerifiedUser
from app.models.source import Channel
from app.models.watchlist import WatchKind, WatchlistItem
from app.queue import enqueue_activity_notification
from app.schemas.auth import MessageOut
from app.schemas.watchlist import WatchlistAddIn, WatchlistItemOut, WatchlistOut
from app.services import epg as epg_svc
from app.services import watchlist as svc

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _when(out: WatchlistItemOut) -> str | None:
    if out.channel_name and out.start is not None:
        return f"{out.channel_name} · {out.start:%a %d %b, %H:%M}"
    return None


async def _to_out(session: SessionDep, item: WatchlistItem) -> WatchlistItemOut:
    out = WatchlistItemOut(
        id=item.id,
        kind=item.kind.value,
        title=item.title_display,
        lead_minutes=item.lead_minutes,
        created_at=item.created_at,
    )
    channel_id = item.channel_id
    start, stop = item.start_utc, item.stop_utc
    if item.kind == WatchKind.by_title:
        nxt = await svc.next_airing(session, item, now=datetime.now(UTC))
        if nxt is not None:
            channel_id, start, stop = nxt.channel_id, nxt.start_utc, nxt.stop_utc

    if channel_id is not None and start is not None and stop is not None:
        channel = await session.get(Channel, channel_id)
        if channel is not None:
            local_start, local_stop, tz = await epg_svc.local_times(session, channel, start, stop)
            out.channel_id = channel.id
            out.channel_name = channel.name
            out.start = local_start
            out.stop = local_stop
            out.timezone = tz
    return out


@router.get("", response_model=WatchlistOut)
async def list_watchlist(user: VerifiedUser, session: SessionDep) -> WatchlistOut:
    items = await svc.list_items(session, user)
    return WatchlistOut(items=[await _to_out(session, i) for i in items])


@router.post("", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
async def add_watchlist(
    body: WatchlistAddIn, user: VerifiedUser, session: SessionDep
) -> WatchlistItemOut:
    try:
        if body.kind == "programme":
            assert body.programme_id is not None
            item, created = await svc.add_programme(
                session, user, programme_id=body.programme_id, lead_minutes=body.lead_minutes
            )
        else:
            assert body.title is not None
            item, created = await svc.add_title(
                session, user, title=body.title, lead_minutes=body.lead_minutes
            )
    except svc.WatchlistError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.flush()
    out = await _to_out(session, item)
    if created:
        when = _when(out)
        if item.kind == WatchKind.programme:
            await enqueue_activity_notification(
                user.tenant_id,
                "reminder_set",
                "Reminder set",
                f"{out.title}\n{when}" if when else out.title,
            )
        else:
            body_lines = ["You'll be notified before every future airing."]
            if when:
                body_lines.append(f"Next: {when}")
            await enqueue_activity_notification(
                user.tenant_id,
                "title_watch_set",
                f"Watching “{out.title}”",
                "\n".join(body_lines),
            )
    return out


@router.delete("/{item_id}", response_model=MessageOut)
async def delete_watchlist(
    item_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    try:
        removed = await svc.remove(session, user, item_id)
    except svc.WatchlistError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await enqueue_activity_notification(
        user.tenant_id,
        "watchlist_remove",
        "Removed from watchlist",
        removed.title_display,
    )
    return MessageOut(message="Removed from your watchlist.")
