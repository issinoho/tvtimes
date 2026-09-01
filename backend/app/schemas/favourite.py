from __future__ import annotations

import uuid

from pydantic import BaseModel


class FavouriteAddIn(BaseModel):
    channel_id: uuid.UUID


class FavouritesOut(BaseModel):
    channel_ids: list[uuid.UUID]
