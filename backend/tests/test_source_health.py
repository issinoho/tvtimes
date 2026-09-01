"""Rolled-up source health (channel fetch + guide feed + staleness)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from app.auth.crypto import encrypt
from app.db import get_sessionmaker
from app.models.epg import EpgSource, EpgStatus
from app.models.source import Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import sources as svc
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


async def _mk(
    *,
    status: SourceStatus = SourceStatus.ok,
    enabled: bool = True,
    refreshed_ago: timedelta | None = timedelta(minutes=30),
    interval: int = 360,
    created_ago: timedelta = timedelta(days=1),
    epg_status: EpgStatus | None = EpgStatus.ok,
    epg_fetched_ago: timedelta | None = timedelta(minutes=30),
    epg_interval: int = 720,
    epg_url: str | None = None,
) -> svc.SourceHealth:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=status,
            enabled=enabled,
            refresh_interval_minutes=interval,
            last_refreshed_at=None if refreshed_ago is None else NOW - refreshed_ago,
            epg_url=epg_url,
            created_at=NOW - created_ago,
        )
        session.add(source)
        await session.flush()
        if epg_status is not None:
            session.add(
                EpgSource(
                    tenant_id=tenant.id,
                    source_id=source.id,
                    url="http://x",
                    last_status=epg_status,
                    last_fetched_at=None if epg_fetched_ago is None else NOW - epg_fetched_ago,
                    refresh_interval_minutes=epg_interval,
                    programme_count=42,
                )
            )
        await session.commit()
        rows = await svc.list_sources(session, tenant.id)
        return (await svc.health_by_source(session, rows, now=NOW))[rows[0].id]


async def test_healthy(db_schema: None) -> None:
    h = await _mk()
    assert h.health == "ok"
    assert h.epg_status == "ok"
    assert h.programme_count == 42


async def test_channel_fetch_error(db_schema: None) -> None:
    assert (await _mk(status=SourceStatus.error)).health == "error"


async def test_guide_feed_error(db_schema: None) -> None:
    assert (await _mk(epg_status=EpgStatus.error)).health == "error"


async def test_stale_channel_refresh(db_schema: None) -> None:
    # 20h since last refresh, interval 6h -> way past 2x
    assert (await _mk(refreshed_ago=timedelta(hours=20))).health == "stale"


async def test_stale_guide_feed(db_schema: None) -> None:
    # 30h since EPG fetch, interval 12h -> past 2x
    assert (await _mk(epg_fetched_ago=timedelta(hours=30))).health == "stale"


async def test_pending_within_grace_is_ok(db_schema: None) -> None:
    h = await _mk(
        status=SourceStatus.pending,
        refreshed_ago=None,
        created_ago=timedelta(minutes=10),
        epg_status=None,
    )
    assert h.health == "ok"


async def test_pending_past_grace_is_stale(db_schema: None) -> None:
    h = await _mk(
        status=SourceStatus.pending,
        refreshed_ago=None,
        created_ago=timedelta(hours=3),
        epg_status=None,
    )
    assert h.health == "stale"


async def test_disabled_source_is_ok(db_schema: None) -> None:
    assert (await _mk(enabled=False, status=SourceStatus.error)).health == "ok"


async def test_advertises_guide_but_none_appeared(db_schema: None) -> None:
    h = await _mk(epg_status=None, epg_url="http://x/epg.xml", created_ago=timedelta(hours=5))
    assert h.health == "stale"
    assert h.epg_status is None


async def test_list_endpoint_carries_health(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    me = (await app_client.get("/api/account/me", headers=h)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    async with get_sessionmaker()() as session:
        session.add(
            Source(
                tenant_id=tenant_id,
                kind=SourceKind.m3u,
                display_name="S",
                config_encrypted=encrypt(json.dumps({"url": "http://x/pl.m3u"})),
                last_status=SourceStatus.error,
                last_error="boom",
            )
        )
        await session.commit()

    row = (await app_client.get("/api/sources", headers=h)).json()[0]
    assert row["health"] == "error"
    assert row["programme_count"] == 0
    assert row["epg_status"] is None
