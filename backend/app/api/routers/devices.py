"""Find-and-approve pairing: the device-facing ``/pairing`` calls (no auth --
the device has nothing yet) and the account's ``/devices`` list."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.auth.deps import SessionDep, VerifiedUser
from app.auth.ratelimit import limiter
from app.config import get_settings
from app.models.device import PairedDevice
from app.schemas.auth import MessageOut
from app.schemas.device import (
    DeviceApproveIn,
    DeviceOut,
    PairingPollIn,
    PairingPollOut,
    PairingStartIn,
    PairingStartOut,
)
from app.services import devices as svc

pairing_router = APIRouter(prefix="/pairing", tags=["pairing"])
devices_router = APIRouter(prefix="/devices", tags=["devices"])


@pairing_router.post("/start", response_model=PairingStartOut)
@limiter.limit("10/minute")
async def start(request: Request, body: PairingStartIn, session: SessionDep) -> PairingStartOut:
    """A device asks to pair. It shows ``code`` on screen and polls with
    ``poll_secret`` every ``interval`` seconds until someone approves the code
    under Settings -> Devices, or ``expires_in`` seconds pass."""
    try:
        started = await svc.start(session, body.name)
    except svc.PairingError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, exc.message) from exc
    return PairingStartOut(
        code=started.code,
        poll_secret=started.poll_secret,
        expires_in=started.expires_in,
        interval=svc.POLL_INTERVAL_S,
    )


@pairing_router.post("/poll", response_model=PairingPollOut)
@limiter.limit("40/minute")
async def poll(request: Request, body: PairingPollIn, session: SessionDep) -> PairingPollOut:
    """``pending`` until approved; then ``approved`` with the device's export
    token, once. 404 once the request has expired or been collected."""
    try:
        collected = await svc.collect(session, body.poll_secret)
    except svc.PairingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    if collected.token is None:
        return PairingPollOut(status="pending")
    return PairingPollOut(
        status="approved",
        token=collected.token,
        origin=get_settings().origin_for(request.headers.get("host")),
    )


def _out(device: PairedDevice) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        name=device.name,
        approved_at=device.approved_at,
        last_used_at=device.last_used_at,
        paired=device.token_hash is not None,
    )


@devices_router.get("", response_model=list[DeviceOut])
async def list_devices(user: VerifiedUser, session: SessionDep) -> list[DeviceOut]:
    return [_out(d) for d in await svc.list_devices(session, user.tenant_id)]


@devices_router.post("", response_model=DeviceOut)
@limiter.limit("10/minute")
async def approve(
    request: Request, body: DeviceApproveIn, user: VerifiedUser, session: SessionDep
) -> DeviceOut:
    """Approve the code a device is showing. It gets its own export token on
    its next poll, a few seconds later."""
    try:
        device = await svc.approve(session, user.tenant_id, body.code)
    except svc.PairingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.message) from exc
    return _out(device)


@devices_router.delete("/{device_id}", response_model=MessageOut)
async def remove(device_id: uuid.UUID, user: VerifiedUser, session: SessionDep) -> MessageOut:
    """Unpair a device. Its token stops working at once."""
    if not await svc.remove(session, user.tenant_id, device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such device")
    return MessageOut(message="Device removed.")
