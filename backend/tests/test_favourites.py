"""Per-user favourite channels."""

from __future__ import annotations

import uuid

import pytest
from app.db import get_sessionmaker
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.services import favourites as svc
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import auth_header, login, register_and_verify


async def _seed() -> dict[str, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        user = User(
            tenant_id=tenant.id,
            email="sam@example.com",
            display_name="Sam",
            email_verified_at=None,
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
        a = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="a",
            name="Alpha",
            stream_ref_encrypted="x",
        )
        b = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="b",
            name="Beta",
            stream_ref_encrypted="x",
        )
        session.add_all([a, b])
        await session.commit()
        return {"tenant": tenant.id, "user": user.id, "a": a.id, "b": b.id}


async def _user(session: AsyncSession, user_id: uuid.UUID) -> User:
    u = await session.get(User, user_id)
    assert u is not None
    return u


async def test_add_is_idempotent_and_ordered(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        await svc.add(session, user, ids["b"])
        await svc.add(session, user, ids["a"])
        await svc.add(session, user, ids["b"])  # again — no-op
        await session.commit()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        assert await svc.list_ids(session, user) == [ids["b"], ids["a"]]  # insertion order


async def test_add_rejects_foreign_channel(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        with pytest.raises(svc.FavouriteError):
            await svc.add(session, user, uuid.uuid4())


async def test_remove_unknown_errors(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        user = await _user(session, ids["user"])
        with pytest.raises(svc.FavouriteError):
            await svc.remove(session, user, ids["a"])


async def test_favourites_api(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
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
        ch = Channel(
            tenant_id=tenant_id,
            source_id=src.id,
            dedupe_key="c",
            name="BBC One",
            stream_ref_encrypted="x",
        )
        session.add(ch)
        await session.commit()
        channel_id = str(ch.id)

    assert (await app_client.get("/api/favourites", headers=h)).json() == {"channel_ids": []}

    created = await app_client.post("/api/favourites", headers=h, json={"channel_id": channel_id})
    assert created.status_code == 201, created.text
    # idempotent
    assert (
        await app_client.post("/api/favourites", headers=h, json={"channel_id": channel_id})
    ).status_code == 201

    assert (await app_client.get("/api/favourites", headers=h)).json() == {
        "channel_ids": [channel_id]
    }

    # unknown channel -> 400
    assert (
        await app_client.post("/api/favourites", headers=h, json={"channel_id": str(uuid.uuid4())})
    ).status_code == 400

    assert (await app_client.delete(f"/api/favourites/{channel_id}", headers=h)).status_code == 200
    assert (await app_client.delete(f"/api/favourites/{channel_id}", headers=h)).status_code == 404
    assert (await app_client.get("/api/favourites", headers=h)).json() == {"channel_ids": []}

    # unauthenticated
    assert (await app_client.get("/api/favourites")).status_code == 401
