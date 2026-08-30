"""A light regression guard: the /guide query stays fast with a realistic
channel/programme count, and returns every requested row."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import epg as svc

CHANNELS = 120
PROGRAMMES_PER_CHANNEL = 40


async def test_guide_scales_to_a_full_lineup(db_schema: None) -> None:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="Big",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        epg = EpgSource(tenant_id=tenant.id, source_id=source.id, url="http://x")
        session.add(epg)
        await session.flush()

        programmes: list[Programme] = []
        for c in range(CHANNELS):
            channel = Channel(
                tenant_id=tenant.id,
                source_id=source.id,
                dedupe_key=f"c{c}",
                name=f"Channel {c}",
                number=c + 1,
                sort_order=c,
                stream_ref_encrypted="x",
            )
            session.add(channel)
            await session.flush()
            for p in range(PROGRAMMES_PER_CHANNEL):
                s = start + timedelta(minutes=30 * p)
                programmes.append(
                    Programme(
                        tenant_id=tenant.id,
                        channel_id=channel.id,
                        epg_source_id=epg.id,
                        start_utc=s,
                        stop_utc=s + timedelta(minutes=30),
                        title=f"Prog {c}-{p}",
                        categories=["News"],
                    )
                )
        session.add_all(programmes)
        await session.commit()
        tenant_id = tenant.id

    async with get_sessionmaker()() as session:
        t0 = time.perf_counter()
        rows = await svc.guide(
            session,
            tenant_id,
            start=start,
            end=start + timedelta(hours=6),
            limit=400,
        )
        elapsed = time.perf_counter() - t0

    assert len(rows) == CHANNELS
    # 6h window / 30-min slots -> 12 programmes per channel visible.
    assert all(len(r.programmes) == 12 for r in rows)
    assert elapsed < 2.0, f"guide query took {elapsed:.2f}s for {CHANNELS} channels"


async def test_guide_channel_filters(db_schema: None) -> None:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        session.add_all(
            Channel(
                tenant_id=tenant.id,
                source_id=source.id,
                dedupe_key=f"c{i}",
                name=f"Chan {i}",
                group_title="Sport" if i % 2 else "News",
                sort_order=i,
                stream_ref_encrypted="x",
            )
            for i in range(6)
        )
        await session.commit()
        tenant_id, source_id = tenant.id, source.id

    async with get_sessionmaker()() as session:
        now = datetime.now(UTC)
        sport = await svc.guide(
            session, tenant_id, start=now, end=now + timedelta(hours=1), group="Sport"
        )
        assert {r.channel.group_title for r in sport} == {"Sport"}

        one = await svc.guide(
            session,
            tenant_id,
            start=now,
            end=now + timedelta(hours=1),
            source_id=uuid.uuid4(),
        )
        assert one == []
        by_source = await svc.guide(
            session, tenant_id, start=now, end=now + timedelta(hours=1), source_id=source_id
        )
        assert len(by_source) == 6
