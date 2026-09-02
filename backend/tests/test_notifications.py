"""Push notification targets: the Apprise service layer and the CRUD API."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import apprise
import pytest
from app.auth.crypto import encrypt
from app.db import get_sessionmaker
from app.models.notification import NotificationTarget
from app.models.tenant import Tenant
from app.services import notify
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

GOTIFY = "gotify://gotify.example.com/AbCdEfGhToken"
NTFY = "ntfy://ntfy.example.com/tvtimes"
GOTIFY_2 = "gotify://gotify.example.com/ZzZzZzZzOther"

Calls = list[dict[str, object]]
State = dict[str, object]


@pytest.fixture
def apprise_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Calls, State]]:
    """Stub ``Apprise.async_notify`` so no packet leaves the box. ``state["result"]``
    drives the outcome: ``True``/``False``/``None`` or an ``Exception`` to raise."""
    calls: Calls = []
    state: State = {"result": True}

    async def _async_notify(self: apprise.Apprise, *args: object, **kwargs: object) -> object:
        call: dict[str, object] = {
            "servers": len(self),
            "title": kwargs.get("title"),
            "body": kwargs.get("body"),
        }
        if kwargs.get("attach"):  # only when set, so plain calls keep a 3-key dict
            call["attach"] = kwargs["attach"]
        calls.append(call)
        result = state["result"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(apprise.Apprise, "async_notify", _async_notify)
    yield calls, state


# --- service: URL parsing ----------------------------------------------------


def test_parse_target_names_service_and_redacts() -> None:
    service, redacted = notify.parse_target(GOTIFY)
    assert service == "Gotify"
    assert redacted.startswith("gotify://gotify.example.com/")
    assert "AbCdEfGhToken" not in redacted


def test_parse_target_rejects_junk() -> None:
    with pytest.raises(notify.InvalidTargetUrl):
        notify.parse_target("hunter2")


def test_describe_target_never_raises() -> None:
    assert notify.describe_target("not a url at all") == ("unknown", "")


# --- service: dispatch fan-out ---------------------------------------------


async def _seed_targets() -> uuid.UUID:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        session.add_all(
            [
                NotificationTarget(
                    tenant_id=tenant.id, label="Gotify", url_encrypted=encrypt(GOTIFY)
                ),
                NotificationTarget(
                    tenant_id=tenant.id,
                    label="ntfy (alerts only)",
                    url_encrypted=encrypt(NTFY),
                    send_reminders=False,
                ),
                NotificationTarget(
                    tenant_id=tenant.id,
                    label="disabled",
                    url_encrypted=encrypt(GOTIFY_2),
                    enabled=False,
                ),
            ]
        )
        await session.commit()
        return tenant.id


async def test_dispatch_reminders_honours_flags(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    calls, _ = apprise_calls
    tenant_id = await _seed_targets()
    async with get_sessionmaker()() as session:
        n = await notify.dispatch(
            session, tenant_id, notify.Notification("Reminder", "soon"), event="reminders"
        )
    assert n == 1  # disabled + send_reminders=False both excluded
    assert calls == [{"servers": 1, "title": "Reminder", "body": "soon"}]


async def test_dispatch_source_alerts_includes_alert_only_target(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    calls, _ = apprise_calls
    tenant_id = await _seed_targets()
    async with get_sessionmaker()() as session:
        n = await notify.dispatch(
            session, tenant_id, notify.Notification("Down", "check"), event="source_alerts"
        )
    assert n == 2  # Gotify + ntfy; the disabled row stays out
    assert calls[0]["servers"] == 2


async def test_dispatch_without_targets_is_a_noop(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    calls, _ = apprise_calls
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="Empty", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        n = await notify.dispatch(
            session, tenant.id, notify.Notification("x", "y"), event="reminders"
        )
    assert n == 0
    assert calls == []


async def test_dispatch_is_fail_open(db_schema: None, apprise_calls: tuple[Calls, State]) -> None:
    calls, state = apprise_calls
    state["result"] = RuntimeError("smtp exploded")
    tenant_id = await _seed_targets()
    async with get_sessionmaker()() as session:
        n = await notify.dispatch(
            session, tenant_id, notify.Notification("x", "y"), event="reminders"
        )
    assert n == 0  # swallowed, not raised
    assert len(calls) == 1


async def test_dispatch_reports_zero_when_apprise_declines(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    _, state = apprise_calls
    state["result"] = False
    tenant_id = await _seed_targets()
    async with get_sessionmaker()() as session:
        n = await notify.dispatch(
            session, tenant_id, notify.Notification("x", "y"), event="reminders"
        )
    assert n == 0


async def test_dispatch_skips_undecryptable_row(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    calls, _ = apprise_calls
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        session.add(
            NotificationTarget(
                tenant_id=tenant.id, label="corrupt", url_encrypted="not-a-fernet-token"
            )
        )
        await session.commit()
        tenant_id = tenant.id
    async with get_sessionmaker()() as session:
        n = await notify.dispatch(
            session, tenant_id, notify.Notification("x", "y"), event="reminders"
        )
    assert n == 0
    assert calls == []  # nothing addable -> async_notify never called


# --- service: activity notifications --------------------------------------


async def _seed_activity_targets(**flags: bool) -> uuid.UUID:
    """Two enabled targets (one with send_reminders off) + one disabled."""
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC", **flags)
        session.add(tenant)
        await session.flush()
        session.add_all(
            [
                NotificationTarget(
                    tenant_id=tenant.id, label="Gotify", url_encrypted=encrypt(GOTIFY)
                ),
                NotificationTarget(
                    tenant_id=tenant.id,
                    label="ntfy (alerts only)",
                    url_encrypted=encrypt(NTFY),
                    send_reminders=False,
                ),
                NotificationTarget(
                    tenant_id=tenant.id,
                    label="disabled",
                    url_encrypted=encrypt(GOTIFY_2),
                    enabled=False,
                ),
            ]
        )
        await session.commit()
        return tenant.id


async def test_notify_activity_is_a_noop_when_category_off(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    calls, _ = apprise_calls
    tenant_id = await _seed_activity_targets(notify_on_play=False)
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        n = await notify.notify_activity(
            session, tenant, "play", notify.Notification("Playing", "BBC One")
        )
    assert n == 0
    assert calls == []


async def test_notify_activity_fans_to_every_enabled_target(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    calls, _ = apprise_calls
    tenant_id = await _seed_activity_targets(notify_on_play=True)
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        n = await notify.notify_activity(
            session, tenant, "play", notify.Notification("Playing", "BBC One")
        )
    # both enabled targets, regardless of their per-target send_* flags; the
    # disabled row stays out
    assert n == 2
    assert calls == [{"servers": 2, "title": "Playing", "body": "BBC One"}]


async def test_notify_activity_is_fail_open(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    _, state = apprise_calls
    state["result"] = RuntimeError("boom")
    tenant_id = await _seed_activity_targets(notify_on_watchlist_remove=True)
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        n = await notify.notify_activity(
            session, tenant, "watchlist_remove", notify.Notification("x", "y")
        )
    assert n == 0  # swallowed, not raised


async def test_worker_activity_notification_job(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    from app.worker import activity_notification

    calls, _ = apprise_calls
    tenant_id = await _seed_activity_targets(notify_on_reminder_set=True)

    await activity_notification({}, str(tenant_id), "reminder_set", "Reminder set", "Later Film")
    assert calls == [{"servers": 2, "title": "Reminder set", "body": "Later Film"}]

    calls.clear()
    await activity_notification({}, str(tenant_id), "not-a-category", "x", "y")
    assert calls == []  # unknown category is ignored


async def test_worker_activity_notification_forwards_image(
    db_schema: None, apprise_calls: tuple[Calls, State]
) -> None:
    from app.worker import activity_notification

    calls, _ = apprise_calls
    tenant_id = await _seed_activity_targets(notify_on_play=True)
    art = "https://image.tmdb.org/t/p/w500/abc.jpg"

    await activity_notification({}, str(tenant_id), "play", "The Thing", "TCM", art)
    assert calls == [{"servers": 2, "title": "The Thing", "body": "TCM", "attach": art}]

    # empty image_url -> no attachment key
    calls.clear()
    await activity_notification({}, str(tenant_id), "play", "The Thing", "TCM", "")
    assert calls == [{"servers": 2, "title": "The Thing", "body": "TCM"}]


# --- API -------------------------------------------------------------------


async def test_notification_target_crud(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    apprise_calls: tuple[Calls, State],
) -> None:
    calls, _ = apprise_calls
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))

    assert (await app_client.get("/api/notification-targets", headers=h)).json() == []

    created = await app_client.post(
        "/api/notification-targets", headers=h, json={"label": "Home Gotify", "url": GOTIFY}
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["service"] == "Gotify"
    assert "AbCdEfGhToken" not in row["redacted_url"]
    assert row["enabled"] and row["send_source_alerts"] and row["send_reminders"]
    target_id = row["id"]

    listed = (await app_client.get("/api/notification-targets", headers=h)).json()
    assert [t["id"] for t in listed] == [target_id]

    # invalid Apprise URL -> 422
    bad = await app_client.post(
        "/api/notification-targets", headers=h, json={"label": "x", "url": "hunter2"}
    )
    assert bad.status_code == 422

    # patch flags + label
    patched = await app_client.patch(
        f"/api/notification-targets/{target_id}",
        headers=h,
        json={"send_reminders": False, "label": "Renamed"},
    )
    assert patched.status_code == 200
    assert patched.json()["send_reminders"] is False
    assert patched.json()["label"] == "Renamed"

    # patch with a bad URL is rejected and changes nothing
    assert (
        await app_client.patch(
            f"/api/notification-targets/{target_id}", headers=h, json={"url": "nope"}
        )
    ).status_code == 422

    # test probe delivers (apprise stubbed to succeed)
    ok = await app_client.post(f"/api/notification-targets/{target_id}/test", headers=h)
    assert ok.status_code == 200
    assert calls and calls[-1]["title"] == "tvtimes test"

    assert (
        await app_client.delete(f"/api/notification-targets/{target_id}", headers=h)
    ).status_code == 200
    assert (
        await app_client.delete(f"/api/notification-targets/{target_id}", headers=h)
    ).status_code == 404
    assert (await app_client.get("/api/notification-targets", headers=h)).json() == []

    assert (await app_client.get("/api/notification-targets")).status_code == 401


async def test_test_probe_returns_502_when_delivery_fails(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    apprise_calls: tuple[Calls, State],
) -> None:
    _, state = apprise_calls
    state["result"] = False
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    target_id = (
        await app_client.post(
            "/api/notification-targets", headers=h, json={"label": "g", "url": GOTIFY}
        )
    ).json()["id"]

    resp = await app_client.post(f"/api/notification-targets/{target_id}/test", headers=h)
    assert resp.status_code == 502


async def test_targets_are_tenant_scoped(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    apprise_calls: tuple[Calls, State],
) -> None:
    await register_and_verify(app_client, captured_emails)
    owner = auth_header(await login(app_client))
    target_id = (
        await app_client.post(
            "/api/notification-targets", headers=owner, json={"label": "g", "url": GOTIFY}
        )
    ).json()["id"]

    await register_and_verify(
        app_client, captured_emails, email="pat@example.com", display_name="Pat"
    )
    other = auth_header(await login(app_client, email="pat@example.com"))

    assert (await app_client.get("/api/notification-targets", headers=other)).json() == []
    assert (
        await app_client.patch(
            f"/api/notification-targets/{target_id}", headers=other, json={"label": "hax"}
        )
    ).status_code == 404
    assert (
        await app_client.delete(f"/api/notification-targets/{target_id}", headers=other)
    ).status_code == 404
    assert (
        await app_client.post(f"/api/notification-targets/{target_id}/test", headers=other)
    ).status_code == 404
