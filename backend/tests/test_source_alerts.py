"""Source health-change detection and the alert-email worker pass."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.auth.crypto import encrypt
from app.db import get_sessionmaker
from app.models.source import Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.services import sources as svc
from sqlalchemy import select

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


async def _seed(
    *,
    status: SourceStatus = SourceStatus.ok,
    alerted: str | None = None,
    refreshed_ago: timedelta | None = timedelta(minutes=30),
    verified: bool = True,
    alerts_enabled: bool = True,
) -> dict[str, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC", source_alerts_enabled=alerts_enabled)
        session.add(tenant)
        await session.flush()
        session.add(
            User(
                tenant_id=tenant.id,
                email="sam@example.com",
                display_name="Sam",
                email_verified_at=NOW if verified else None,
            )
        )
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="My playlist",
            config_encrypted=encrypt(json.dumps({"url": "http://x/list.m3u"})),
            last_status=status,
            last_error="502 Bad Gateway" if status == SourceStatus.error else None,
            alerted_health=alerted,
            last_refreshed_at=None if refreshed_ago is None else NOW - refreshed_ago,
            created_at=NOW - timedelta(days=2),
        )
        session.add(source)
        await session.commit()
        return {"tenant": tenant.id, "source": source.id}


async def _scan() -> list[tuple[str, str | None, str]]:
    async with get_sessionmaker()() as session:
        changes = await svc.scan_health_changes(session, now=NOW)
        await session.commit()
        return [(c.health, c.previous, c.reason) for c in changes]


async def test_fresh_ok_source_is_stamped_silently(db_schema: None) -> None:
    ids = await _seed()
    assert await _scan() == []
    async with get_sessionmaker()() as session:
        src = await session.get(Source, ids["source"])
        assert src is not None and src.alerted_health == "ok"


async def test_new_error_is_reported(db_schema: None) -> None:
    await _seed(status=SourceStatus.error)
    changes = await _scan()
    assert len(changes) == 1
    health, prev, reason = changes[0]
    assert health == "error" and prev is None
    assert "502 Bad Gateway" in reason


async def test_already_alerted_error_is_quiet(db_schema: None) -> None:
    await _seed(status=SourceStatus.error, alerted="error")
    assert await _scan() == []


async def test_recovery_is_reported_once(db_schema: None) -> None:
    ids = await _seed(status=SourceStatus.ok, alerted="error")
    changes = await _scan()
    assert len(changes) == 1
    assert changes[0][0] == "ok" and changes[0][1] == "error"
    assert "recovered" in changes[0][2]
    # second scan: nothing left to say
    assert await _scan() == []
    async with get_sessionmaker()() as session:
        src = await session.get(Source, ids["source"])
        assert src is not None and src.alerted_health == "ok"


async def test_stale_transition_is_reported(db_schema: None) -> None:
    await _seed(refreshed_ago=timedelta(hours=20), alerted="ok")  # interval 360m default
    changes = await _scan()
    assert len(changes) == 1
    assert changes[0][0] == "stale"
    assert "hasn't refreshed" in changes[0][2]


async def test_worker_emails_once_then_stamps(
    db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import worker

    await _seed(status=SourceStatus.error)
    outbox: list[dict[str, str]] = []

    async def _capture(*, to: str, subject: str, body_text: str) -> None:
        outbox.append({"to": to, "subject": subject, "body": body_text})

    monkeypatch.setattr(worker, "send_email", _capture)
    monkeypatch.setattr(worker, "_now", lambda: NOW)

    await worker.source_alerts({})
    assert len(outbox) == 1
    assert outbox[0]["to"] == "sam@example.com"
    assert "My playlist" in outbox[0]["subject"]
    assert "502 Bad Gateway" in outbox[0]["body"]
    assert "/sources" in outbox[0]["body"]

    await worker.source_alerts({})  # no further transition
    assert len(outbox) == 1


async def test_worker_skips_unverified_users(
    db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import worker

    await _seed(status=SourceStatus.error, verified=False)
    outbox: list[dict[str, str]] = []

    async def _capture(*, to: str, subject: str, body_text: str) -> None:
        outbox.append({"to": to})

    monkeypatch.setattr(worker, "send_email", _capture)
    monkeypatch.setattr(worker, "_now", lambda: NOW)

    await worker.source_alerts({})
    assert outbox == []
    # but the marker is still stamped so it won't re-alert once verified
    async with get_sessionmaker()() as session:
        src = (await session.scalars(select(Source))).one()
        assert src.alerted_health == "error"


async def test_worker_skips_tenant_with_alerts_off(
    db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import worker

    await _seed(status=SourceStatus.error, alerts_enabled=False)
    outbox: list[str] = []

    async def _capture(*, to: str, subject: str, body_text: str) -> None:
        outbox.append(to)

    monkeypatch.setattr(worker, "send_email", _capture)
    monkeypatch.setattr(worker, "_now", lambda: NOW)

    await worker.source_alerts({})
    assert outbox == []
    # marker still stamped, so flipping alerts back on won't replay old state
    async with get_sessionmaker()() as session:
        src = (await session.scalars(select(Source))).one()
        assert src.alerted_health == "error"
