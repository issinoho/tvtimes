"""Per-tenant push notification targets (Apprise URLs).

CRUD plus a ``/test`` probe. Delivery lives in ``app.services.notify`` and is
wired into the worker's ``source_alerts`` and ``reminders`` jobs — it runs
alongside the existing email path, never replacing it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.crypto import decrypt, encrypt
from app.auth.deps import SessionDep, VerifiedUser
from app.models.notification import NotificationTarget
from app.schemas.auth import MessageOut
from app.schemas.notification import (
    NotificationTargetIn,
    NotificationTargetOut,
    NotificationTargetPatch,
)
from app.services import notify

router = APIRouter(prefix="/notification-targets", tags=["notifications"])


def _out(row: NotificationTarget) -> NotificationTargetOut:
    try:
        url = decrypt(row.url_encrypted)
    except ValueError:  # corrupt row / rotated key
        url = ""
    service, redacted = notify.describe_target(url)
    return NotificationTargetOut(
        id=row.id,
        label=row.label,
        service=service,
        redacted_url=redacted,
        enabled=row.enabled,
        send_source_alerts=row.send_source_alerts,
        send_reminders=row.send_reminders,
        created_at=row.created_at,
    )


def _validate(url: str) -> None:
    try:
        notify.parse_target(url)
    except notify.InvalidTargetUrl as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


async def _target(
    session: SessionDep, user: VerifiedUser, target_id: uuid.UUID
) -> NotificationTarget:
    row = await session.get(NotificationTarget, target_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown notification target")
    return row


@router.get("", response_model=list[NotificationTargetOut])
async def list_targets(user: VerifiedUser, session: SessionDep) -> list[NotificationTargetOut]:
    rows = await session.scalars(
        select(NotificationTarget)
        .where(NotificationTarget.tenant_id == user.tenant_id)
        .order_by(NotificationTarget.created_at)
    )
    return [_out(r) for r in rows]


@router.post("", response_model=NotificationTargetOut, status_code=status.HTTP_201_CREATED)
async def create_target(
    body: NotificationTargetIn, user: VerifiedUser, session: SessionDep
) -> NotificationTargetOut:
    _validate(body.url)
    row = NotificationTarget(
        tenant_id=user.tenant_id,
        label=body.label,
        url_encrypted=encrypt(body.url.strip()),
        enabled=body.enabled,
        send_source_alerts=body.send_source_alerts,
        send_reminders=body.send_reminders,
    )
    session.add(row)
    await session.flush()
    return _out(row)


@router.patch("/{target_id}", response_model=NotificationTargetOut)
async def update_target(
    target_id: uuid.UUID,
    body: NotificationTargetPatch,
    user: VerifiedUser,
    session: SessionDep,
) -> NotificationTargetOut:
    row = await _target(session, user, target_id)
    if body.url is not None:
        _validate(body.url)
        row.url_encrypted = encrypt(body.url.strip())
    if body.label is not None:
        row.label = body.label
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.send_source_alerts is not None:
        row.send_source_alerts = body.send_source_alerts
    if body.send_reminders is not None:
        row.send_reminders = body.send_reminders
    await session.flush()
    return _out(row)


@router.delete("/{target_id}", response_model=MessageOut)
async def delete_target(
    target_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    row = await _target(session, user, target_id)
    await session.delete(row)
    return MessageOut(message="Notification target removed.")


@router.post("/{target_id}/test", response_model=MessageOut)
async def test_target(target_id: uuid.UUID, user: VerifiedUser, session: SessionDep) -> MessageOut:
    row = await _target(session, user, target_id)
    if await notify.send_test(row):
        return MessageOut(message="Test notification sent.")
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "Apprise couldn't deliver the test — check the URL and that the server is reachable.",
    )
