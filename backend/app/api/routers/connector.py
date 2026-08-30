"""Connector-facing endpoints — outbound HTTPS only, from the LAN agent."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.auth.deps import SessionDep
from app.auth.ratelimit import limiter
from app.models.connector import Connector
from app.schemas.connector import (
    HeartbeatIn,
    HeartbeatOut,
    LineupIn,
    LineupOut,
    PairIn,
    PairOut,
)
from app.services import connectors as svc
from app.services.connectors import HEARTBEAT_INTERVAL
from app.services.epg import ensure_epg_source_for

router = APIRouter(prefix="/connector", tags=["connector"])


async def current_connector(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Connector:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing connector token")
    token = authorization.split(" ", 1)[1].strip()
    connector = await svc.authenticate(session, token)
    if connector is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid connector token")
    return connector


ConnectorDep = Annotated[Connector, Depends(current_connector)]


@router.post("/pair", response_model=PairOut)
@limiter.limit("10/minute")
async def pair(request: Request, body: PairIn, session: SessionDep) -> PairOut:
    try:
        paired = await svc.pair(session, body.code)
    except svc.PairingInvalid as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.message) from exc
    return PairOut(
        connector_id=paired.connector_id,
        token=paired.token,
        heartbeat_interval=HEARTBEAT_INTERVAL,
    )


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    body: HeartbeatIn, connector: ConnectorDep, session: SessionDep
) -> HeartbeatOut:
    await svc.heartbeat(session, connector, version=body.version)
    return HeartbeatOut(heartbeat_interval=HEARTBEAT_INTERVAL)


@router.post("/lineup", response_model=LineupOut)
async def submit_lineup(body: LineupIn, connector: ConnectorDep, session: SessionDep) -> LineupOut:
    lineup = svc.Lineup(
        device_id=body.device_id,
        friendly_name=body.friendly_name,
        model=body.model,
        tuner_count=body.tuner_count,
        epg_url=body.epg_url,
        channels=[
            svc.LineupChannel(name=c.name, stream_url=c.stream_url, number=c.number, hd=c.hd)
            for c in body.channels
        ],
    )
    source = await svc.submit_lineup(session, connector, lineup)
    await ensure_epg_source_for(session, source)
    return LineupOut(channels=source.channel_count)
