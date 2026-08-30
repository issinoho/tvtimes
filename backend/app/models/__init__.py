"""ORM models.

Every model module is imported here so ``app.db.Base.metadata`` is fully
populated for Alembic autogenerate and for ``create_all`` in tests.

Models are added per phase:
  phase 2 -> tenant, user, credentials, session, token, audit
  phase 3 -> source, channel, connector
  phase 4 -> epg_source, programme
  phase 6 -> tmdb_enrichment
"""

from __future__ import annotations

from app.db import Base
from app.models.audit import AuditLog
from app.models.credentials import PasswordCredential, TotpSecret, WebAuthnCredential
from app.models.session import AuthSession
from app.models.tenant import Tenant
from app.models.token import (
    EmailToken,
    EmailTokenPurpose,
    WebAuthnChallenge,
    WebAuthnChallengeKind,
)
from app.models.user import User

__all__ = [
    "AuditLog",
    "AuthSession",
    "Base",
    "EmailToken",
    "EmailTokenPurpose",
    "PasswordCredential",
    "Tenant",
    "TotpSecret",
    "User",
    "WebAuthnChallenge",
    "WebAuthnChallengeKind",
    "WebAuthnCredential",
]
