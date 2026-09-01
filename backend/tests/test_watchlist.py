"""Watchlist CRUD, the reminder-due query, and the worker's email pass."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.models.watchlist import WatchlistNotification
from app.services import watchlist as svc
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import auth_header, login, register_and_verify

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)


async def _seed(*, verified: bool = True, ch_a_shift_seconds: int = 0) -> dict[str, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        user = User(
            tenant_id=tenant.id,
            email="sam@example.com",
            display_name="Sam",
            email_verified_at=NOW if verified else None,
        )
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add_all([user, source])
        await session.flush()
        epg = EpgSource(tenant_id=tenant.id, source_id=source.id, url="http://x")
        ch_a = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="a",
            name="Alpha",
            stream_ref_encrypted="x",
            clock_shift_seconds=ch_a_shift_seconds,
        )
        ch_b = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="b",
            name="Beta",
            stream_ref_encrypted="x",
        )
        session.add_all([epg, ch_a, ch_b])
        await session.flush()

        # "Interstellar" airs at NOW+10min on Alpha and NOW+90min on Beta.
        p1 = Programme(
            tenant_id=tenant.id,
            channel_id=ch_a.id,
            epg_source_id=epg.id,
            start_utc=NOW + timedelta(minutes=10),
            stop_utc=NOW + timedelta(minutes=130),
            title="Interstellar",
            is_movie=True,
        )
        p2 = Programme(
            tenant_id=tenant.id,
            channel_id=ch_b.id,
            epg_source_id=epg.id,
            start_utc=NOW + timedelta(minutes=90),
            stop_utc=NOW + timedelta(minutes=210),
            title="Interstellar",
            is_movie=True,
        )
        session.add_all([p1, p2])
        await session.commit()
        return {
            "tenant": tenant.id,
            "user": user.id,
            "ch_a": ch_a.id,
            "ch_b": ch_b.id,
            "p1": p1.id,
            "p2": p2.id,
        }


async def _user(session: AsyncSession, user_id: uuid.UUID) -> User:
    u = await session.get(User, user_id)
    assert u is not None
    return u


# --- CRUD ------------------------------------------------------------------


async def test_add_is_idempotent(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        a = await svc.add_programme(session, user, programme_id=ids["p1"])
        b = await svc.add_programme(session, user, programme_id=ids["p1"])
        t1 = await svc.add_title(session, user, title="  Interstellar ")
        t2 = await svc.add_title(session, user, title="interstellar")
        await session.commit()
    assert a.id == b.id
    assert t1.id == t2.id
    assert t1.title_norm == "interstellar"


async def test_add_programme_rejects_foreign(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        with pytest.raises(svc.WatchlistError):
            await svc.add_programme(session, user, programme_id=uuid.uuid4())


async def test_remove_checks_owner(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        item = await svc.add_title(session, user, title="Interstellar")
        await session.commit()
        item_id = item.id
    async with get_sessionmaker()() as session:
        stranger = User(
            tenant_id=ids["tenant"], email="x@y.z", display_name="X", email_verified_at=NOW
        )
        session.add(stranger)
        await session.flush()
        with pytest.raises(svc.WatchlistError):
            await svc.remove(session, stranger, item_id)


# --- due_reminders -------------------------------------------------------------


async def test_programme_reminder_fires_once_in_window(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add_programme(session, user, programme_id=ids["p1"], lead_minutes=15)
        await session.commit()

    # 20 min before start (start = NOW+10): outside the 15-min lead window.
    async with get_sessionmaker()() as session:
        assert await svc.due_reminders(session, now=NOW - timedelta(minutes=10)) == []

    # 5 min before start: inside. Fire, record, and it must not fire again.
    async with get_sessionmaker()() as session:
        due = await svc.due_reminders(session, now=NOW + timedelta(minutes=5))
        assert len(due) == 1 and due[0].title == "Interstellar"
        await svc.mark_sent(session, due[0].item, key=due[0].key, now=NOW + timedelta(minutes=5))
        await session.commit()

    async with get_sessionmaker()() as session:
        assert await svc.due_reminders(session, now=NOW + timedelta(minutes=6)) == []


async def test_title_reminder_matches_each_airing(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add_title(session, user, title="Interstellar", lead_minutes=15)
        await session.commit()

    # NOW+5: only the Alpha airing (starts NOW+10) is inside its lead window.
    async with get_sessionmaker()() as session:
        due = await svc.due_reminders(session, now=NOW + timedelta(minutes=5))
        assert [d.channel_id for d in due] == [ids["ch_a"]]
        await svc.mark_sent(session, due[0].item, key=due[0].key, now=NOW + timedelta(minutes=5))
        await session.commit()

    # NOW+80: now the Beta airing (starts NOW+90) is inside; Alpha already sent.
    async with get_sessionmaker()() as session:
        due = await svc.due_reminders(session, now=NOW + timedelta(minutes=80))
        assert [d.channel_id for d in due] == [ids["ch_b"]]


async def test_programme_reminder_uses_the_channel_clock_shift(db_schema: None) -> None:
    # Alpha is corrected +1h, so p1's raw start NOW+10 airs (and is shown) at NOW+70.
    ids = await _seed(ch_a_shift_seconds=3600)
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add_programme(session, user, programme_id=ids["p1"], lead_minutes=15)
        await session.commit()

    # NOW+5 is 5 min after the *raw* start but 65 min before the corrected one:
    # under the old raw comparison this fired; it must not now.
    async with get_sessionmaker()() as session:
        assert await svc.due_reminders(session, now=NOW + timedelta(minutes=5)) == []

    # NOW+60: inside the 15-min lead before the corrected NOW+70 start.
    async with get_sessionmaker()() as session:
        due = await svc.due_reminders(session, now=NOW + timedelta(minutes=60))
        assert len(due) == 1 and due[0].title == "Interstellar"
        # the airing key stays keyed on the raw start, so the ledger is stable
        assert due[0].key == svc.airing_key(ids["ch_a"], NOW + timedelta(minutes=10))


async def test_title_reminder_uses_the_channel_clock_shift(db_schema: None) -> None:
    ids = await _seed(ch_a_shift_seconds=3600)  # Alpha +1h; Beta unshifted
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add_title(session, user, title="Interstellar", lead_minutes=15)
        await session.commit()

    # NOW+60: Alpha's corrected start is NOW+70 -> inside its lead; Beta's is NOW+90.
    async with get_sessionmaker()() as session:
        due = await svc.due_reminders(session, now=NOW + timedelta(minutes=60))
        assert [d.channel_id for d in due] == [ids["ch_a"]]

    # NOW+80: Beta (unshifted, starts NOW+90) is now inside; Alpha's window has passed.
    async with get_sessionmaker()() as session:
        due = await svc.due_reminders(session, now=NOW + timedelta(minutes=80))
        assert [d.channel_id for d in due] == [ids["ch_b"]]


async def test_unverified_user_is_skipped(db_schema: None) -> None:
    ids = await _seed(verified=False)
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add_programme(session, user, programme_id=ids["p1"], lead_minutes=15)
        await session.commit()
    async with get_sessionmaker()() as session:
        assert await svc.due_reminders(session, now=NOW + timedelta(minutes=5)) == []


# --- worker --------------------------------------------------------------------


async def test_worker_emails_and_records(db_schema: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import worker

    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add_programme(session, user, programme_id=ids["p1"], lead_minutes=15)
        await session.commit()

    outbox: list[dict[str, str]] = []

    async def _capture(*, to: str, subject: str, body_text: str) -> None:
        outbox.append({"to": to, "subject": subject, "body": body_text})

    monkeypatch.setattr(worker, "send_email", _capture)
    monkeypatch.setattr(worker, "_now", lambda: NOW + timedelta(minutes=5))

    await worker.reminders({})

    assert len(outbox) == 1
    assert outbox[0]["to"] == "sam@example.com"
    assert "Interstellar" in outbox[0]["subject"] and "Alpha" in outbox[0]["subject"]

    async with get_sessionmaker()() as session:
        ledger = list(await session.scalars(select(WatchlistNotification)))
        assert len(ledger) == 1

    # Second run in the same window sends nothing.
    await worker.reminders({})
    assert len(outbox) == 1


async def test_worker_dedupes_push_across_users(
    db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import apprise
    from app import worker
    from app.auth.crypto import encrypt
    from app.models.notification import NotificationTarget

    ids = await _seed()
    async with get_sessionmaker()() as session:
        user1 = await _user(session, ids["user"])
        await svc.add_programme(session, user1, programme_id=ids["p1"], lead_minutes=15)
        user2 = User(
            tenant_id=ids["tenant"],
            email="pat@example.com",
            display_name="Pat",
            email_verified_at=NOW,
        )
        session.add(user2)
        await session.flush()
        await svc.add_programme(session, user2, programme_id=ids["p1"], lead_minutes=15)
        session.add(
            NotificationTarget(
                tenant_id=ids["tenant"],
                label="Gotify",
                url_encrypted=encrypt("gotify://gotify.example.com/AbCdToken"),
            )
        )
        await session.commit()

    emails: list[str] = []
    pushes: list[dict[str, str]] = []

    async def _capture_email(*, to: str, subject: str, body_text: str) -> None:
        emails.append(to)

    async def _fake_notify(self: apprise.Apprise, *a: object, **k: object) -> bool:
        pushes.append({"title": str(k.get("title")), "body": str(k.get("body"))})
        return True

    monkeypatch.setattr(worker, "send_email", _capture_email)
    monkeypatch.setattr(apprise.Apprise, "async_notify", _fake_notify)
    monkeypatch.setattr(worker, "_now", lambda: NOW + timedelta(minutes=5))

    await worker.reminders({})

    assert sorted(emails) == ["pat@example.com", "sam@example.com"]  # every watcher emailed
    assert len(pushes) == 1  # the tenant's device is notified once
    assert "Interstellar" in pushes[0]["title"]


# --- API ---------------------------------------------------------------------


async def test_watchlist_api(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    access = await login(app_client)
    h = auth_header(access)
    me = (await app_client.get("/api/account/me", headers=h)).json()
    tenant_id = uuid.UUID(me["tenant_id"])

    async with get_sessionmaker()() as session:
        src = Source(
            tenant_id=tenant_id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(src)
        await session.flush()
        epg = EpgSource(tenant_id=tenant_id, source_id=src.id, url="http://x")
        ch = Channel(
            tenant_id=tenant_id,
            source_id=src.id,
            dedupe_key="c",
            name="BBC One",
            stream_ref_encrypted="x",
        )
        session.add_all([epg, ch])
        await session.flush()
        prog = Programme(
            tenant_id=tenant_id,
            channel_id=ch.id,
            epg_source_id=epg.id,
            start_utc=datetime.now(UTC) + timedelta(days=1),
            stop_utc=datetime.now(UTC) + timedelta(days=1, hours=1),
            title="Later Film",
            is_movie=True,
        )
        session.add(prog)
        await session.commit()
        programme_id = str(prog.id)

    created = await app_client.post(
        "/api/watchlist", headers=h, json={"kind": "programme", "programme_id": programme_id}
    )
    assert created.status_code == 201, created.text
    assert created.json()["title"] == "Later Film"
    assert created.json()["channel_name"] == "BBC One"

    title_item = await app_client.post(
        "/api/watchlist", headers=h, json={"kind": "title", "title": "Later Film"}
    )
    assert title_item.status_code == 201
    # the title watch resolves its next airing for the list UI
    assert title_item.json()["start"] is not None

    listing = (await app_client.get("/api/watchlist", headers=h)).json()
    assert len(listing["items"]) == 2

    # bad payloads
    assert (
        await app_client.post("/api/watchlist", headers=h, json={"kind": "programme"})
    ).status_code == 422
    assert (
        await app_client.post("/api/watchlist", headers=h, json={"kind": "title", "title": " "})
    ).status_code == 422

    item_id = created.json()["id"]
    assert (await app_client.delete(f"/api/watchlist/{item_id}", headers=h)).status_code == 200
    assert (await app_client.delete(f"/api/watchlist/{uuid.uuid4()}", headers=h)).status_code == 404
    assert len((await app_client.get("/api/watchlist", headers=h)).json()["items"]) == 1
