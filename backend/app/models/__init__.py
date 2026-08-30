"""ORM models.

Import every model module here so that ``app.db.Base.metadata`` is fully
populated for Alembic autogenerate and for ``create_all`` in tests.

Models are added per phase:
  phase 2 -> tenant, user, credentials, sessions
  phase 3 -> source, channel, connector
  phase 4 -> epg_source, programme
  phase 6 -> tmdb_enrichment
"""

from __future__ import annotations

from app.db import Base

__all__ = ["Base"]
