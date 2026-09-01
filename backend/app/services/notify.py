"""Push notifications via Apprise.

One URL scheme reaches Gotify, ntfy, Discord, Telegram, Pushover and ~100 other
services, so a tenant configures free-form Apprise URLs rather than per-service
forms. Targets are stored per tenant (Fernet-encrypted — the URL usually carries
a token) and delivery fans out to every enabled one.

This runs *alongside* the email path (``app.auth.email``) — it never replaces
it. Like email it is **fail-open**: a bad target or a dead server is logged and
skipped, never raised, so a broken notifier can't wedge the worker.

Targets are deliberately **not** routed through ``app.ingest.ssrf`` — they are
operator-chosen outbound endpoints (typically a Gotify/ntfy box on the LAN),
the same rationale as ``app.ingest.hdhomerun``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

import apprise
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt
from app.logging import get_logger
from app.models.notification import NotificationTarget

_log = get_logger("services.notify")

Event = Literal["source_alerts", "reminders"]


@dataclass(slots=True)
class Notification:
    title: str
    body: str


class InvalidTargetUrl(ValueError):
    """Apprise could not parse the supplied URL."""


def parse_target(url: str) -> tuple[str, str]:
    """Validate an Apprise URL.

    Returns ``(service_name, privacy-redacted URL)`` — e.g. ``("Gotify",
    "gotify://gotify.lan/a...n/")``. Raises :class:`InvalidTargetUrl` if Apprise
    doesn't recognise it.
    """
    ap = apprise.Apprise()
    if not ap.add(url.strip()):
        raise InvalidTargetUrl("That doesn't look like a valid Apprise URL.")
    plugin = next(iter(ap), None)
    if plugin is None:  # pragma: no cover - add() succeeded, so this won't happen
        raise InvalidTargetUrl("That doesn't look like a valid Apprise URL.")
    service = str(getattr(plugin, "service_name", "") or "notification")
    redacted = str(plugin.url(privacy=True)).split("?", 1)[0]  # type: ignore[no-untyped-call]
    return service, redacted


def describe_target(url: str) -> tuple[str, str]:
    """Like :func:`parse_target` but never raises — for rendering stored rows
    whose URL might no longer parse (Apprise upgrade, key rotation)."""
    try:
        return parse_target(url)
    except Exception:
        return "unknown", ""


async def _targets(
    session: AsyncSession, tenant_id: uuid.UUID, event: Event
) -> list[NotificationTarget]:
    flag = (
        NotificationTarget.send_source_alerts
        if event == "source_alerts"
        else NotificationTarget.send_reminders
    )
    rows = await session.scalars(
        select(NotificationTarget)
        .where(
            NotificationTarget.tenant_id == tenant_id,
            NotificationTarget.enabled.is_(True),
            flag.is_(True),
        )
        .order_by(NotificationTarget.created_at)
    )
    return list(rows)


def _client(urls: list[str]) -> apprise.Apprise:
    ap = apprise.Apprise()
    for url in urls:
        try:
            ap.add(url)
        except Exception as exc:  # pragma: no cover - add() swallows most of these
            _log.warning("notify.bad_target", error=f"{type(exc).__name__}: {exc}")
    return ap


async def dispatch(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    notification: Notification,
    *,
    event: Event,
) -> int:
    """Fan ``notification`` out to the tenant's enabled targets for ``event``.

    Returns the number of targets Apprise accepted it for. Fail-open: any
    failure logs and returns ``0`` rather than raising.
    """
    targets = await _targets(session, tenant_id, event)
    if not targets:
        return 0

    urls: list[str] = []
    for t in targets:
        try:
            urls.append(decrypt(t.url_encrypted))
        except ValueError as exc:  # corrupt row / rotated key
            _log.warning("notify.undecryptable_target", target_id=str(t.id), error=str(exc))
    ap = _client(urls)
    if not len(ap):
        return 0

    try:
        ok = await ap.async_notify(title=notification.title, body=notification.body)
    except Exception as exc:
        _log.error(
            "notify.dispatch_failed",
            tenant_id=str(tenant_id),
            notify_event=event,
            error=f"{type(exc).__name__}: {exc}",
        )
        return 0

    delivered = len(ap) if ok else 0
    _log.info(
        "notify.dispatch",
        tenant_id=str(tenant_id),
        notify_event=event,
        targets=len(ap),
        delivered=delivered,
    )
    return delivered


async def send_test(target: NotificationTarget) -> bool:
    """Fire a one-off test notification at a single target. Returns whether
    Apprise accepted it. Never raises."""
    try:
        url = decrypt(target.url_encrypted)
    except ValueError as exc:
        _log.warning("notify.test_undecryptable", target_id=str(target.id), error=str(exc))
        return False
    ap = _client([url])
    if not len(ap):
        return False
    try:
        return bool(
            await ap.async_notify(
                title="tvtimes test",
                body=f"Test notification for “{target.label}”. If you can read this, it works.",
            )
        )
    except Exception as exc:
        _log.warning(
            "notify.test_failed",
            target_id=str(target.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        return False
