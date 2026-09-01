"""Per-user favourite channels — CRUD only. Consumers (guide, Tonight) read
the id list and filter/sort client-side."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.favourite import FavouriteChannel
from app.models.source import Channel
from app.models.user import User


class FavouriteError(Exception):
    """Bad request — surfaced as 400/404 by the router."""


async def list_ids(session: AsyncSession, user: User) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(FavouriteChannel.channel_id)
        .where(FavouriteChannel.user_id == user.id)
        .order_by(FavouriteChannel.created_at)
    )
    return list(rows)


async def add(session: AsyncSession, user: User, channel_id: uuid.UUID) -> None:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.tenant_id != user.tenant_id:
        raise FavouriteError("Unknown channel")
    existing = await session.scalar(
        select(FavouriteChannel).where(
            FavouriteChannel.user_id == user.id,
            FavouriteChannel.channel_id == channel_id,
        )
    )
    if existing is not None:
        return
    session.add(FavouriteChannel(tenant_id=user.tenant_id, user_id=user.id, channel_id=channel_id))
    await session.flush()


async def remove(session: AsyncSession, user: User, channel_id: uuid.UUID) -> None:
    row = await session.scalar(
        select(FavouriteChannel).where(
            FavouriteChannel.user_id == user.id,
            FavouriteChannel.channel_id == channel_id,
        )
    )
    if row is None:
        raise FavouriteError("Not a favourite")
    await session.delete(row)
