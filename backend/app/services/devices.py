"""Find-and-approve pairing for TVs and other players (see app.models.device).

The flow, from the device's side, is three unauthenticated calls:

1. ``start(name)`` -> a code to show on screen and a poll secret to keep.
2. Someone signed in enters the code under Settings -> Devices (``approve``).
3. ``collect(poll_secret)`` -> "pending" until then; once approved, the
   device's own export token, exactly once.

Only sha256 hashes of the poll secret and the token are stored. A code is
8 characters from a 30-letter alphabet (~6.6e11 values) and lives 10
minutes, approving needs a verified signed-in user, and every endpoint is
rate-limited, so guessing someone else's code is not a practical attack --
and a wrongly approved code would only hand a *stranger's* TV the guesser's
own guide.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.device import PairedDevice

_log = get_logger("services.devices")

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 8
PAIRING_TTL = timedelta(minutes=10)
POLL_INTERVAL_S = 3
# Pending requests anyone on the network can create; beyond this, start()
# refuses until some expire. Enough for any household, small enough that a
# flood can't grow the table.
MAX_PENDING = 50
TOUCH_INTERVAL = timedelta(minutes=1)


class PairingError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Started:
    code: str
    poll_secret: str
    expires_in: int


@dataclass(frozen=True)
class Collected:
    """``token`` is None while the code is still waiting for approval."""

    token: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalise_code(code: str) -> str:
    """What a person types: any case, with spaces or a dash in the middle."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


async def _sweep(session: AsyncSession) -> None:
    """Drop requests that expired before anyone approved (or collected) them."""
    await session.execute(
        delete(PairedDevice).where(
            PairedDevice.token_hash.is_(None),
            PairedDevice.expires_at.is_not(None),
            PairedDevice.expires_at <= _now(),
        )
    )


async def start(session: AsyncSession, name: str) -> Started:
    await _sweep(session)
    pending = await session.scalar(
        select(func.count()).select_from(PairedDevice).where(PairedDevice.tenant_id.is_(None))
    )
    if (pending or 0) >= MAX_PENDING:
        raise PairingError("Too many pairing requests are waiting. Try again in a few minutes.")
    code = _new_code()
    while await session.scalar(select(PairedDevice.id).where(PairedDevice.pairing_code == code)):
        code = _new_code()
    poll_secret = secrets.token_urlsafe(32)
    session.add(
        PairedDevice(
            name=name.strip()[:120] or "TV",
            pairing_code=code,
            poll_secret_hash=_hash(poll_secret),
            expires_at=_now() + PAIRING_TTL,
        )
    )
    await session.flush()
    return Started(code=code, poll_secret=poll_secret, expires_in=int(PAIRING_TTL.total_seconds()))


async def approve(session: AsyncSession, tenant_id: uuid.UUID, code: str) -> PairedDevice:
    device: PairedDevice | None = await session.scalar(
        select(PairedDevice).where(PairedDevice.pairing_code == normalise_code(code))
    )
    if (
        device is None
        or device.tenant_id is not None
        or device.expires_at is None
        or device.expires_at <= _now()
    ):
        raise PairingError("That code is invalid or has expired. Check the TV for the current one.")
    device.tenant_id = tenant_id
    device.pairing_code = None
    device.approved_at = _now()
    # The device now has PAIRING_TTL to come and collect its token.
    device.expires_at = _now() + PAIRING_TTL
    await session.flush()
    _log.info("devices.approved", device_id=str(device.id), tenant_id=str(tenant_id))
    return device


async def collect(session: AsyncSession, poll_secret: str) -> Collected:
    device: PairedDevice | None = await session.scalar(
        select(PairedDevice).where(PairedDevice.poll_secret_hash == _hash(poll_secret))
    )
    if device is None or device.expires_at is None or device.expires_at <= _now():
        raise PairingError("This pairing request has expired. Start again on the TV.")
    if device.tenant_id is None:
        return Collected(token=None)
    raw = secrets.token_urlsafe(32)
    device.token_hash = _hash(raw)
    device.poll_secret_hash = None
    device.expires_at = None
    await session.flush()
    return Collected(token=raw)


async def list_devices(session: AsyncSession, tenant_id: uuid.UUID) -> Sequence[PairedDevice]:
    """Paired devices, plus approved ones that haven't collected their token yet."""
    await _sweep(session)
    return (
        await session.scalars(
            select(PairedDevice)
            .where(PairedDevice.tenant_id == tenant_id)
            .order_by(PairedDevice.approved_at.desc())
        )
    ).all()


async def remove(session: AsyncSession, tenant_id: uuid.UUID, device_id: uuid.UUID) -> bool:
    """Unpair: the device's token stops working at once."""
    result = await session.execute(
        delete(PairedDevice).where(
            PairedDevice.id == device_id, PairedDevice.tenant_id == tenant_id
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def device_for_token(session: AsyncSession, raw: str) -> PairedDevice | None:
    if not raw:
        return None
    device: PairedDevice | None = await session.scalar(
        select(PairedDevice).where(
            PairedDevice.token_hash == _hash(raw), PairedDevice.tenant_id.is_not(None)
        )
    )
    return device


async def touch(session: AsyncSession, device: PairedDevice) -> None:
    now = _now()
    if device.last_used_at is not None and now - device.last_used_at < TOUCH_INTERVAL:
        return
    device.last_used_at = now
    await session.flush()
