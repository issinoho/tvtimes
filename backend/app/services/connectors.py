"""Connector pairing, heartbeat, and lineup ingestion.

A connector never receives an inbound connection: it pairs with a short code,
then pushes heartbeats and HDHomeRun lineups over outbound HTTPS. A lineup
materialises a ``kind=connector`` :class:`Source` and its channels, reusing the
Phase 3 channel model and the Phase 4 EPG pipeline.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt, encrypt
from app.logging import get_logger
from app.models.connector import Connector, ConnectorStatus
from app.models.source import Channel, Source, SourceKind, SourceStatus

_log = get_logger("services.connectors")

PAIRING_TTL = timedelta(minutes=15)
HEARTBEAT_INTERVAL = 60  # seconds the agent should wait between heartbeats
OFFLINE_AFTER = timedelta(seconds=HEARTBEAT_INTERVAL * 3)
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


class ConnectorError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PairingInvalid(ConnectorError):
    def __init__(self) -> None:
        super().__init__("That pairing code is invalid or has expired.")


class ConnectorNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def status_of(connector: Connector, now: datetime | None = None) -> ConnectorStatus:
    if connector.token_hash is None:
        return ConnectorStatus.unpaired
    now = now or _now()
    if connector.last_seen_at is not None and now - connector.last_seen_at < OFFLINE_AFTER:
        return ConnectorStatus.online
    return ConnectorStatus.offline


# --- CRUD (tenant-facing) --------------------------------------------------


async def create_connector(session: AsyncSession, *, tenant_id: uuid.UUID, name: str) -> Connector:
    connector = Connector(
        tenant_id=tenant_id,
        name=name.strip() or "Home network",
        pairing_code=_new_code(),
        pairing_expires_at=_now() + PAIRING_TTL,
    )
    session.add(connector)
    await session.flush()
    return connector


async def list_connectors(session: AsyncSession, tenant_id: uuid.UUID) -> Sequence[Connector]:
    rows = await session.scalars(
        select(Connector)
        .where(Connector.tenant_id == tenant_id)
        .order_by(Connector.created_at.desc())
    )
    return list(rows)


async def get_connector(
    session: AsyncSession, tenant_id: uuid.UUID, connector_id: uuid.UUID
) -> Connector:
    row = await session.get(Connector, connector_id)
    if row is None or row.tenant_id != tenant_id:
        raise ConnectorNotFound
    return row


async def delete_connector(session: AsyncSession, connector: Connector) -> None:
    # Drop the materialised source too.
    source = await _source_for(session, connector)
    if source is not None:
        await session.delete(source)
    await session.delete(connector)


async def regenerate_pairing_code(session: AsyncSession, connector: Connector) -> None:
    connector.pairing_code = _new_code()
    connector.pairing_expires_at = _now() + PAIRING_TTL


# --- connector-facing ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paired:
    connector_id: uuid.UUID
    token: str


async def pair(session: AsyncSession, code: str) -> Paired:
    connector = await session.scalar(
        select(Connector).where(Connector.pairing_code == code.strip().upper())
    )
    if (
        connector is None
        or connector.pairing_expires_at is None
        or connector.pairing_expires_at <= _now()
    ):
        raise PairingInvalid
    raw_token = secrets.token_urlsafe(32)
    connector.token_hash = _hash(raw_token)
    connector.pairing_code = None
    connector.pairing_expires_at = None
    connector.last_seen_at = _now()
    _log.info("connector.paired", connector_id=str(connector.id))
    return Paired(connector_id=connector.id, token=raw_token)


async def authenticate(session: AsyncSession, raw_token: str) -> Connector | None:
    row: Connector | None = await session.scalar(
        select(Connector).where(Connector.token_hash == _hash(raw_token))
    )
    return row


async def heartbeat(session: AsyncSession, connector: Connector, *, version: str | None) -> None:
    connector.last_seen_at = _now()
    if version:
        connector.version = version[:40]


# --- lineup ingestion --------------------------------------------------------


@dataclass(slots=True)
class LineupChannel:
    name: str
    stream_url: str
    number: int | None = None
    hd: bool = False


@dataclass(slots=True)
class Lineup:
    device_id: str
    friendly_name: str
    model: str | None = None
    tuner_count: int | None = None
    epg_url: str | None = None
    channels: list[LineupChannel] = field(default_factory=list)


async def source_id_for(session: AsyncSession, connector: Connector) -> uuid.UUID | None:
    source = await _source_for(session, connector)
    return source.id if source else None


async def _source_for(
    session: AsyncSession, connector: Connector, device_id: str | None = None
) -> Source | None:
    rows = await session.scalars(
        select(Source).where(
            Source.tenant_id == connector.tenant_id, Source.kind == SourceKind.connector
        )
    )
    for source in rows:
        cfg = json.loads(decrypt(source.config_encrypted))
        if cfg.get("connector_id") == str(connector.id) and (
            device_id is None or cfg.get("device_id") == device_id
        ):
            return source
    return None


async def submit_lineup(session: AsyncSession, connector: Connector, lineup: Lineup) -> Source:
    connector.last_seen_at = _now()
    _merge_discovered(connector, lineup)

    source = await _source_for(session, connector, lineup.device_id)
    if source is None:
        source = Source(
            tenant_id=connector.tenant_id,
            kind=SourceKind.connector,
            display_name=lineup.friendly_name or "HDHomeRun",
            config_encrypted=encrypt(
                json.dumps({"connector_id": str(connector.id), "device_id": lineup.device_id})
            ),
        )
        session.add(source)
        await session.flush()
    else:
        source.display_name = lineup.friendly_name or source.display_name

    await session.execute(delete(Channel).where(Channel.source_id == source.id))
    seen: set[str] = set()
    for order, ch in enumerate(lineup.channels or []):
        key = (str(ch.number) if ch.number is not None else ch.name.strip().lower())[:400]
        if not key or key in seen:
            continue
        seen.add(key)
        session.add(
            Channel(
                tenant_id=connector.tenant_id,
                source_id=source.id,
                dedupe_key=key,
                ext_id=str(ch.number) if ch.number is not None else None,
                name=ch.name[:400],
                number=ch.number,
                is_hd=ch.hd or "HD" in ch.name.upper().split(),
                sort_order=order,
                stream_ref_encrypted=encrypt(ch.stream_url),
                last_seen_at=_now(),
            )
        )

    source.channel_count = len(seen)
    source.epg_url = (lineup.epg_url or "").strip() or None
    source.last_status = SourceStatus.ok
    source.last_error = None
    source.last_refreshed_at = _now()
    _log.info(
        "connector.lineup",
        connector_id=str(connector.id),
        device=lineup.device_id,
        channels=source.channel_count,
    )
    return source


def _merge_discovered(connector: Connector, lineup: Lineup) -> None:
    entry = {
        "device_id": lineup.device_id,
        "friendly_name": lineup.friendly_name,
        "model": lineup.model,
        "tuner_count": lineup.tuner_count,
    }
    others = [d for d in connector.discovered if d.get("device_id") != lineup.device_id]
    connector.discovered = [*others, entry]
