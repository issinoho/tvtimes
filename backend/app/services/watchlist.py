"""Watchlist CRUD and the reminder-due query.

The worker (``app.worker.reminders``) drives delivery; this module owns the
data and the "what should fire now" logic.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epg import Programme
from app.models.source import Channel, Source
from app.models.user import User
from app.models.watchlist import WatchKind, WatchlistItem, WatchlistNotification
from app.services.epg import MAX_CLOCK_SHIFT, _shift_seconds

MAX_LEAD_MINUTES = 180
# How far past "now" the title-match scan looks — covers the largest lead plus a
# margin for a late cron tick.
_HORIZON_SLACK = timedelta(minutes=10)
_LEDGER_RETENTION = timedelta(days=30)


class WatchlistError(Exception):
    """Bad request — surfaced as 400/404 by the router."""


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).casefold()


def airing_key(channel_id: uuid.UUID, start_utc: datetime) -> str:
    return f"{channel_id}:{int(start_utc.timestamp())}"


# --- CRUD --------------------------------------------------------------------


async def list_items(session: AsyncSession, user: User) -> list[WatchlistItem]:
    rows = await session.scalars(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.created_at.desc())
    )
    return list(rows)


async def add_programme(
    session: AsyncSession, user: User, *, programme_id: uuid.UUID, lead_minutes: int = 15
) -> WatchlistItem:
    programme = await session.get(Programme, programme_id)
    if programme is None or programme.tenant_id != user.tenant_id:
        raise WatchlistError("Unknown programme")
    existing = await session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.kind == WatchKind.programme,
            WatchlistItem.channel_id == programme.channel_id,
            WatchlistItem.start_utc == programme.start_utc,
        )
    )
    if existing is not None:
        return existing
    item = WatchlistItem(
        tenant_id=user.tenant_id,
        user_id=user.id,
        kind=WatchKind.programme,
        title_display=programme.title,
        channel_id=programme.channel_id,
        start_utc=programme.start_utc,
        stop_utc=programme.stop_utc,
        lead_minutes=_clamp_lead(lead_minutes),
    )
    session.add(item)
    await session.flush()
    return item


async def add_title(
    session: AsyncSession, user: User, *, title: str, lead_minutes: int = 15
) -> WatchlistItem:
    display = title.strip()
    norm = normalize_title(display)
    if not norm:
        raise WatchlistError("Empty title")
    existing = await session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.kind == WatchKind.by_title,
            WatchlistItem.title_norm == norm,
        )
    )
    if existing is not None:
        return existing
    item = WatchlistItem(
        tenant_id=user.tenant_id,
        user_id=user.id,
        kind=WatchKind.by_title,
        title_display=display,
        title_norm=norm,
        lead_minutes=_clamp_lead(lead_minutes),
    )
    session.add(item)
    await session.flush()
    return item


async def remove(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    item = await session.get(WatchlistItem, item_id)
    if item is None or item.user_id != user.id:
        raise WatchlistError("Unknown watchlist item")
    await session.delete(item)


def _clamp_lead(minutes: int) -> int:
    return max(1, min(MAX_LEAD_MINUTES, minutes))


# --- reminder-due query -----------------------------------------------------


@dataclass(slots=True)
class DueReminder:
    item: WatchlistItem
    user: User
    channel_id: uuid.UUID
    start_utc: datetime
    stop_utc: datetime
    title: str

    @property
    def key(self) -> str:
        return airing_key(self.channel_id, self.start_utc)


async def due_reminders(session: AsyncSession, *, now: datetime) -> list[DueReminder]:
    """Every (item, airing) whose reminder window contains ``now`` and that has
    not been emailed yet."""
    items = list(await session.scalars(select(WatchlistItem)))
    if not items:
        return []

    users = {
        u.id: u
        for u in await session.scalars(select(User).where(User.id.in_({i.user_id for i in items})))
    }
    recent = await session.scalars(
        select(WatchlistNotification).where(WatchlistNotification.sent_at > now - timedelta(days=2))
    )
    sent: set[tuple[uuid.UUID, str]] = {(n.watchlist_item_id, n.airing_key) for n in recent}

    horizon = now + timedelta(minutes=MAX_LEAD_MINUTES) + _HORIZON_SLACK
    title_items = [i for i in items if i.kind == WatchKind.by_title and i.title_norm]
    upcoming: list[Programme] = []
    if title_items:
        # Widened by the max clock-shift: a corrected channel's raw start_utc
        # can sit up to a day either side of the reminder's real fire time.
        upcoming = list(
            await session.scalars(
                select(Programme).where(
                    Programme.start_utc > now - MAX_CLOCK_SHIFT,
                    Programme.start_utc <= horizon + MAX_CLOCK_SHIFT,
                )
            )
        )

    # A channel's clock-shift correction is what the user saw in the guide, so
    # the reminder fires relative to ``start_utc + shift``, not the raw feed
    # time. The airing_key stays raw so the send-once ledger is unaffected.
    shift_ids = {i.channel_id for i in items if i.kind == WatchKind.programme and i.channel_id}
    shift_ids |= {p.channel_id for p in upcoming}
    channels = (
        {c.id: c for c in await session.scalars(select(Channel).where(Channel.id.in_(shift_ids)))}
        if shift_ids
        else {}
    )
    sources = (
        {
            s.id: s
            for s in await session.scalars(
                select(Source).where(Source.id.in_({c.source_id for c in channels.values()}))
            )
        }
        if channels
        else {}
    )

    def _shift(channel_id: uuid.UUID) -> timedelta:
        channel = channels.get(channel_id)
        if channel is None:
            return timedelta()
        return timedelta(seconds=_shift_seconds(channel, sources.get(channel.source_id)))

    due: list[DueReminder] = []

    for item in items:
        user = users.get(item.user_id)
        if user is None or not user.is_verified:
            continue
        lead = timedelta(minutes=item.lead_minutes)

        if item.kind == WatchKind.programme:
            if item.channel_id is None or item.start_utc is None or item.stop_utc is None:
                continue
            eff_start = item.start_utc + _shift(item.channel_id)
            if not (eff_start - lead <= now < eff_start):
                continue
            key = airing_key(item.channel_id, item.start_utc)
            if (item.id, key) in sent:
                continue
            due.append(
                DueReminder(
                    item=item,
                    user=user,
                    channel_id=item.channel_id,
                    start_utc=item.start_utc,
                    stop_utc=item.stop_utc,
                    title=item.title_display,
                )
            )
        else:
            for p in upcoming:
                if p.tenant_id != item.tenant_id:
                    continue
                if normalize_title(p.title) != item.title_norm:
                    continue
                eff_start = p.start_utc + _shift(p.channel_id)
                if not (eff_start - lead <= now < eff_start):
                    continue
                key = airing_key(p.channel_id, p.start_utc)
                if (item.id, key) in sent:
                    continue
                due.append(
                    DueReminder(
                        item=item,
                        user=user,
                        channel_id=p.channel_id,
                        start_utc=p.start_utc,
                        stop_utc=p.stop_utc,
                        title=p.title,
                    )
                )

    return due


async def mark_sent(session: AsyncSession, item: WatchlistItem, *, key: str, now: datetime) -> None:
    session.add(WatchlistNotification(watchlist_item_id=item.id, airing_key=key, sent_at=now))


async def prune(session: AsyncSession, *, now: datetime | None = None) -> None:
    cutoff = (now or datetime.now(UTC)) - _LEDGER_RETENTION
    stale = await session.scalars(
        select(WatchlistNotification).where(WatchlistNotification.sent_at < cutoff)
    )
    for row in stale:
        await session.delete(row)


async def next_airing(
    session: AsyncSession, item: WatchlistItem, *, now: datetime
) -> Programme | None:
    """The soonest upcoming programme a title watch would match — for the list
    UI. ``None`` for a programme item or when nothing is scheduled. "Soonest"
    is by the channel's corrected (clock-shifted) airtime, matching the guide."""
    if item.kind != WatchKind.by_title or not item.title_norm:
        return None
    rows = list(
        await session.scalars(
            select(Programme)
            .where(
                Programme.tenant_id == item.tenant_id,
                Programme.start_utc > now - MAX_CLOCK_SHIFT,
            )
            .order_by(Programme.start_utc)
        )
    )
    matches = [p for p in rows if normalize_title(p.title) == item.title_norm]
    if not matches:
        return None
    channels = {
        c.id: c
        for c in await session.scalars(
            select(Channel).where(Channel.id.in_({p.channel_id for p in matches}))
        )
    }
    sources = {
        s.id: s
        for s in await session.scalars(
            select(Source).where(Source.id.in_({c.source_id for c in channels.values()}))
        )
    }

    def _eff(p: Programme) -> datetime:
        channel = channels.get(p.channel_id)
        shift = _shift_seconds(channel, sources.get(channel.source_id)) if channel else 0
        return p.start_utc + timedelta(seconds=shift)

    future = [(p, _eff(p)) for p in matches if _eff(p) > now]
    if not future:
        return None
    return min(future, key=lambda t: t[1])[0]
