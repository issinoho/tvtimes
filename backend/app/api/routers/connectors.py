"""Tenant-facing connector management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import SessionDep, VerifiedUser
from app.config import get_settings
from app.models.connector import Connector
from app.schemas.auth import MessageOut
from app.schemas.connector import ConnectorCreatedOut, ConnectorCreateIn, ConnectorOut
from app.services import connectors as svc
from app.services.connectors import HEARTBEAT_INTERVAL

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _out(session_connector: Connector, source_id: uuid.UUID | None = None) -> ConnectorOut:
    return ConnectorOut(
        id=session_connector.id,
        name=session_connector.name,
        status=svc.status_of(session_connector).value,
        version=session_connector.version,
        last_seen_at=session_connector.last_seen_at,
        pairing_code=session_connector.pairing_code,
        pairing_expires_at=session_connector.pairing_expires_at,
        devices=session_connector.discovered,
        source_id=source_id,
        created_at=session_connector.created_at,
    )


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(user: VerifiedUser, session: SessionDep) -> list[ConnectorOut]:
    rows = await svc.list_connectors(session, user.tenant_id)
    return [_out(c, await svc.source_id_for(session, c)) for c in rows]


@router.post("", response_model=ConnectorCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_connector(
    body: ConnectorCreateIn, user: VerifiedUser, session: SessionDep
) -> ConnectorCreatedOut:
    connector = await svc.create_connector(session, tenant_id=user.tenant_id, name=body.name)
    await session.flush()
    origin = get_settings().public_origin.rstrip("/")
    base = _out(connector)
    return ConnectorCreatedOut(
        **base.model_dump(),
        install_hint=(f"tvtimes-connector pair --server {origin} --code {connector.pairing_code}"),
    )


async def _load(session: SessionDep, user: VerifiedUser, connector_id: uuid.UUID) -> Connector:
    try:
        return await svc.get_connector(session, user.tenant_id, connector_id)
    except svc.ConnectorNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown connector") from exc


@router.post("/{connector_id}/pairing-code", response_model=ConnectorOut)
async def new_pairing_code(
    connector_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> ConnectorOut:
    connector = await _load(session, user, connector_id)
    await svc.regenerate_pairing_code(session, connector)
    return _out(connector, await svc.source_id_for(session, connector))


@router.delete("/{connector_id}", response_model=MessageOut)
async def delete_connector(
    connector_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    connector = await _load(session, user, connector_id)
    await svc.delete_connector(session, connector)
    return MessageOut(message="Connector removed.")


# re-exported for the connector-facing router
__all__ = ["HEARTBEAT_INTERVAL", "router"]
