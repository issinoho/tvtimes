"""Per-user favourite channels."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import SessionDep, VerifiedUser
from app.schemas.auth import MessageOut
from app.schemas.favourite import FavouriteAddIn, FavouritesOut
from app.services import favourites as svc

router = APIRouter(prefix="/favourites", tags=["favourites"])


@router.get("", response_model=FavouritesOut)
async def list_favourites(user: VerifiedUser, session: SessionDep) -> FavouritesOut:
    return FavouritesOut(channel_ids=await svc.list_ids(session, user))


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def add_favourite(
    body: FavouriteAddIn, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    try:
        await svc.add(session, user, body.channel_id)
    except svc.FavouriteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return MessageOut(message="Added to favourites.")


@router.delete("/{channel_id}", response_model=MessageOut)
async def delete_favourite(
    channel_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    try:
        await svc.remove(session, user, channel_id)
    except svc.FavouriteError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return MessageOut(message="Removed from favourites.")
