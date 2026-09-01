from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import epg as svc


async def _seed(
    *, tz_override: str | None, source_shift: int = 0, channel_shift: int = 0
) -> tuple[uuid.UUID, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="Europe/London")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            timezone_override=tz_override,
            clock_shift_seconds=source_shift,
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        channel = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="c1",
            name="Chan",
            stream_ref_encrypted="x",
            clock_shift_seconds=channel_shift,
        )
        epg = EpgSource(tenant_id=tenant.id, source_id=source.id, url="http://x")
        session.add_all([channel, epg])
        await session.flush()
        session.add(
            Programme(
                tenant_id=tenant.id,
                channel_id=channel.id,
                epg_source_id=epg.id,
                start_utc=datetime(2026, 1, 15, 19, tzinfo=UTC),
                stop_utc=datetime(2026, 1, 15, 20, tzinfo=UTC),
                title="Show",
            )
        )
        await session.commit()
        return tenant.id, channel.id


async def _schedule(channel_id: uuid.UUID) -> tuple[datetime, str]:
    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, channel_id)
        assert channel is not None
        triples, tz = await svc.channel_schedule(
            session,
            channel,
            start=datetime(2026, 1, 15, tzinfo=UTC),
            end=datetime(2026, 1, 16, tzinfo=UTC),
        )
        assert len(triples) == 1
        return triples[0][1], tz


async def test_falls_back_to_tenant_timezone(db_schema: None) -> None:
    _t, channel_id = await _seed(tz_override=None)
    local, tz = await _schedule(channel_id)
    assert tz == "Europe/London"
    assert local.hour == 19 and local.utcoffset() == timedelta(0)  # GMT in January


async def test_source_timezone_override_wins(db_schema: None) -> None:
    _t, channel_id = await _seed(tz_override="America/New_York")
    local, tz = await _schedule(channel_id)
    assert tz == "America/New_York"
    assert local.hour == 14  # 19:00 UTC - 5h (EST)


async def test_channel_clock_shift_applies_on_top(db_schema: None) -> None:
    _t, channel_id = await _seed(tz_override="UTC", channel_shift=3600)
    local, _tz = await _schedule(channel_id)
    assert local.hour == 20  # 19:00 UTC + 1h shift


async def test_channel_shift_overrides_source_shift(db_schema: None) -> None:
    _t, channel_id = await _seed(tz_override="UTC", source_shift=1800, channel_shift=-3600)
    local, _tz = await _schedule(channel_id)
    assert local.hour == 18  # channel's -1h wins over the source's +30m


# --- clock shift must move the *window* filter too, not just formatting -------


async def _seed_many(*, channel_shift: int, starts_hours: list[int]) -> tuple[uuid.UUID, uuid.UUID]:
    """A UTC channel with ``channel_shift`` seconds of correction and a 1h
    programme starting at each ``2026-01-15 HH:00`` UTC."""
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            timezone_override="UTC",
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        channel = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="c1",
            name="Chan",
            stream_ref_encrypted="x",
            clock_shift_seconds=channel_shift,
        )
        epg = EpgSource(tenant_id=tenant.id, source_id=source.id, url="http://x")
        session.add_all([channel, epg])
        await session.flush()
        for h in starts_hours:
            session.add(
                Programme(
                    tenant_id=tenant.id,
                    channel_id=channel.id,
                    epg_source_id=epg.id,
                    start_utc=datetime(2026, 1, 15, h, tzinfo=UTC),
                    stop_utc=datetime(2026, 1, 15, h + 1, tzinfo=UTC),
                    title=f"P{h:02d}",
                )
            )
        await session.commit()
        return tenant.id, channel.id


async def test_channel_schedule_window_accounts_for_shift(db_schema: None) -> None:
    # +3h correction: raw 10:00 airs (shows) at 13:00, raw 05:00 shows at 08:00.
    _tenant_id, channel_id = await _seed_many(channel_shift=3 * 3600, starts_hours=[5, 10, 14])
    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, channel_id)
        assert channel is not None
        triples, _tz = await svc.channel_schedule(
            session,
            channel,
            start=datetime(2026, 1, 15, 12, tzinfo=UTC),
            end=datetime(2026, 1, 15, 18, tzinfo=UTC),
        )
    titles = {t[0].title for t in triples}
    # raw 10:00 -> shown 13:00 (in), raw 14:00 -> shown 17:00 (in), raw 05:00 -> shown 08:00 (out)
    assert titles == {"P10", "P14"}


async def test_guide_grid_window_accounts_for_shift(db_schema: None) -> None:
    tenant_id, _channel_id = await _seed_many(channel_shift=3 * 3600, starts_hours=[5, 10, 14])
    async with get_sessionmaker()() as session:
        rows = await svc.guide(
            session,
            tenant_id,
            start=datetime(2026, 1, 15, 12, tzinfo=UTC),
            end=datetime(2026, 1, 15, 18, tzinfo=UTC),
        )
    assert len(rows) == 1
    shown = {p.title for p, _s, _e in rows[0].programmes}
    assert shown == {"P10", "P14"}
    # and their rendered start reflects the +3h shift
    starts = {p.title: s.hour for p, s, _e in rows[0].programmes}
    assert starts == {"P10": 13, "P14": 17}
