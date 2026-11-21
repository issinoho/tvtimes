"""Machine-to-machine hooks, authenticated by a per-source token rather than a
user session -- for other systems that keep a source's address current."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.auth.deps import ClientMetaDep, SessionDep
from app.auth.ratelimit import limiter
from app.logging import get_logger
from app.models.audit import AuditLog
from app.models.source import Source
from app.queue import enqueue_source_refresh
from app.schemas.source import SourceUrlPushIn, SourceUrlPushOut
from app.services import sources as svc

router = APIRouter(prefix="/hooks", tags=["hooks"])
_log = get_logger("hooks")

HOOK_LIMIT = "30/minute"


async def update_token_source(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Source:
    # Header only, never ``?token=``: unlike a tuner, the caller can send one,
    # and a query-string token ends up in every proxy's access log.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing update token")
    source = await svc.source_for_update_token(session, authorization.split(" ", 1)[1].strip())
    if source is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid update token")
    return source


UpdateTokenSource = Annotated[Source, Depends(update_token_source)]


@router.post(
    "/source-url",
    response_model=SourceUrlPushOut,
    responses={
        401: {"description": "Missing or invalid update token"},
        422: {"description": "The URL was rejected (bad scheme, private address, ...)"},
    },
)
@limiter.limit(HOOK_LIMIT)
async def push_source_url(
    request: Request,
    body: SourceUrlPushIn,
    source: UpdateTokenSource,
    session: SessionDep,
    meta: ClientMetaDep,
) -> SourceUrlPushOut:
    """Point the token's source at a new playlist / server / portal URL.

    Send ``Authorization: Bearer <token>`` (from the source's page) and
    ``{"url": "..."}``. Other connection settings are kept. The URL is checked
    exactly as an edit in the app is; if it differs from the stored one the
    source is refreshed in place, so channels keep their guide data. Sending
    the URL it already has changes nothing, so it is safe to push on a timer."""
    try:
        changed = await svc.push_source_url(session, source, body.url.strip())
    except svc.UpdateTokenUnsupported as exc:  # a token can't be minted for these
        raise HTTPException(status.HTTP_409_CONFLICT, "This source has no URL to update") from exc
    if changed:
        # Host only: a dynamic URL usually carries a signed token in its query.
        host = urlsplit(body.url.strip()).hostname
        session.add(
            AuditLog(
                event="source.url_pushed",
                tenant_id=source.tenant_id,
                ip=meta.ip,
                user_agent=meta.user_agent,
                detail={"source_id": str(source.id), "host": host},
            )
        )
        # Commit before enqueueing: the worker reads the source in its own
        # session and would otherwise refresh from the old URL.
        await session.commit()
        _log.info("hooks.source_url_pushed", source_id=str(source.id), host=host)
        await enqueue_source_refresh(source.id)
    return SourceUrlPushOut(source_id=source.id, changed=changed)
