"""Watch state: ingesting reported viewing intervals, and deriving which
programmes those intervals mean you watched.

The split matters. A reporter (tvdinner, via its ``--report-watch-state``)
sends *intervals* — "this channel, from 20:58 to 21:47" — and nothing about
programmes. Watched-ness is derived here, on read, by overlapping those
intervals against whatever the guide currently says was on. So an EPG
re-ingest, or a corrected clock-shift, changes the answer for free, and no
stored row goes stale or dangles when ``programme`` rows are replaced.

Auth is the tenant's export token, the same one the playlist/guide/watchlist
feeds use — see ``app.api.routers.exports``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epg import Programme
from app.models.source import Channel, Source
from app.models.watch import WatchEvent
from app.services.epg import _shift_seconds

# How much of a programme has to be covered before it counts as watched. A
# viewer who joins late or drops out before the credits still watched it; a
# two-minute channel-flip past it did not.
WATCHED_FRACTION = 0.5
# ...but a long programme shouldn't need half of it: 30 minutes of a
# three-hour film is a real watch. Either threshold satisfies.
WATCHED_MINIMUM = timedelta(minutes=30)

# An interval longer than this is almost certainly a player left running at an
# empty screen overnight rather than a real viewing, and would otherwise mark a
# whole evening's schedule watched.
MAX_EVENT_DURATION = timedelta(hours=6)


@dataclass(slots=True)
class ReportedWatch:
    """One interval as posted by a reporter, before it's been validated
    against the tenant's channels."""

    channel_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    title: str | None = None
    device: str | None = None


async def record_watch_events(
    session: AsyncSession, tenant_id: uuid.UUID, reported: list[ReportedWatch]
) -> tuple[int, int]:
    """Upsert reported intervals, returning ``(stored, skipped)``.

    Idempotent on ``(channel_id, started_at)``: a reporter that resends its
    whole log — or retries a failed batch — updates in place rather than
    piling up duplicates. Anything referencing a channel outside this tenant,
    or with a non-positive or implausibly long duration, is skipped rather
    than failing the batch: one bad row from a reporter must not cost the
    good ones.
    """
    if not reported:
        return 0, 0

    channel_ids = {r.channel_id for r in reported}
    mine = set(
        await session.scalars(
            select(Channel.id).where(Channel.tenant_id == tenant_id, Channel.id.in_(channel_ids))
        )
    )

    existing = {
        (e.channel_id, e.started_at): e
        for e in await session.scalars(
            select(WatchEvent).where(
                WatchEvent.tenant_id == tenant_id,
                WatchEvent.channel_id.in_(mine or {uuid.uuid4()}),
            )
        )
    }

    stored = skipped = 0
    seen: set[tuple[uuid.UUID, datetime]] = set()
    for row in reported:
        duration = row.ended_at - row.started_at
        if row.channel_id not in mine or duration <= timedelta(0) or duration > MAX_EVENT_DURATION:
            skipped += 1
            continue
        key = (row.channel_id, row.started_at)
        if key in seen:  # duplicate inside this very batch
            skipped += 1
            continue
        seen.add(key)

        event = existing.get(key)
        if event is None:
            session.add(
                WatchEvent(
                    tenant_id=tenant_id,
                    channel_id=row.channel_id,
                    started_at=row.started_at,
                    ended_at=row.ended_at,
                    title=row.title,
                    device=row.device,
                )
            )
        else:
            # A later report of the same start means the viewing ran on.
            event.ended_at = max(event.ended_at, row.ended_at)
            event.title = row.title or event.title
            event.device = row.device or event.device
        stored += 1
    return stored, skipped


async def watched_programme_ids(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    programmes: list[Programme],
) -> set[uuid.UUID]:
    """Which of ``programmes`` a reported interval covers enough of to count.

    Takes the programmes the caller already loaded rather than querying its
    own window, so a guide render costs one extra query for the events rather
    than one per row. Empty set when nothing has ever been reported — the
    common case for an account with no player wired up, and cheap.
    """
    if not programmes:
        return set()

    channel_ids = {p.channel_id for p in programmes}
    span_start = min(p.start_utc for p in programmes)
    span_end = max(p.stop_utc for p in programmes)

    events = list(
        await session.scalars(
            select(WatchEvent).where(
                WatchEvent.tenant_id == tenant_id,
                WatchEvent.channel_id.in_(channel_ids),
                # Widened by the cap so an interval starting before the window
                # but running into it is still considered.
                WatchEvent.ended_at > span_start,
                WatchEvent.started_at < span_end + MAX_EVENT_DURATION,
            )
        )
    )
    if not events:
        return set()

    by_channel: dict[uuid.UUID, list[WatchEvent]] = {}
    for event in events:
        by_channel.setdefault(event.channel_id, []).append(event)

    # Reported intervals are corrected times (the reporter played the export
    # feed, whose guide is already shifted), so a raw programme row has to be
    # shifted the same way before they're comparable.
    shifts = await _channel_shifts(session, channel_ids)

    watched: set[uuid.UUID] = set()
    for programme in programmes:
        events_here = by_channel.get(programme.channel_id)
        if not events_here:
            continue
        shift = shifts.get(programme.channel_id, timedelta(0))
        start, stop = programme.start_utc + shift, programme.stop_utc + shift
        length = stop - start
        if length <= timedelta(0):
            continue
        covered = sum(
            (
                max(timedelta(0), min(stop, e.ended_at) - max(start, e.started_at))
                for e in events_here
            ),
            timedelta(0),
        )
        if covered >= min(length * WATCHED_FRACTION, WATCHED_MINIMUM):
            watched.add(programme.id)
    return watched


async def _channel_shifts(
    session: AsyncSession, channel_ids: set[uuid.UUID]
) -> dict[uuid.UUID, timedelta]:
    channels = list(await session.scalars(select(Channel).where(Channel.id.in_(channel_ids))))
    if not channels:
        return {}
    sources = {
        s.id: s
        for s in await session.scalars(
            select(Source).where(Source.id.in_({c.source_id for c in channels}))
        )
    }
    return {c.id: timedelta(seconds=_shift_seconds(c, sources.get(c.source_id))) for c in channels}


async def prune_watch_events(
    session: AsyncSession, tenant_id: uuid.UUID, *, keep: timedelta = timedelta(days=90)
) -> int:
    """Drop intervals older than ``keep``. Watched-ness is only ever asked
    about the guide window, so history beyond that is dead weight."""
    cutoff = datetime.now(UTC) - keep
    stale = list(
        await session.scalars(
            select(WatchEvent).where(
                WatchEvent.tenant_id == tenant_id, WatchEvent.ended_at < cutoff
            )
        )
    )
    for event in stale:
        await session.delete(event)
    return len(stale)
