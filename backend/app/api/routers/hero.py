"""The cinematic programme-detail (hero) endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import SessionDep, VerifiedUser
from app.queue import enqueue_programme_enrich
from app.schemas.tmdb import CastMember, EnrichmentOut, HeroOut
from app.services import epg as epg_svc
from app.services import tmdb as tmdb_svc

router = APIRouter(tags=["hero"])


@router.get("/guide/programme/{programme_id}/hero", response_model=HeroOut)
async def programme_hero(
    programme_id: uuid.UUID, user: VerifiedUser, session: SessionDep
) -> HeroOut:
    hero = await tmdb_svc.hero_for(session, user.tenant_id, programme_id)
    if hero is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown programme")

    if hero.enriching:
        await enqueue_programme_enrich(user.tenant_id, programme_id)

    p = hero.programme
    local_start, local_stop, _tz = await epg_svc.local_times(
        session, hero.channel, p.start_utc, p.stop_utc
    )

    enrichment = None
    e = hero.enrichment
    if e is not None and not e.negative:
        enrichment = EnrichmentOut(
            tmdb_id=e.tmdb_id,
            title=e.title,
            release_year=e.release_year,
            overview=e.overview,
            tagline=e.tagline,
            rating=e.rating,
            runtime=e.runtime,
            director=e.director,
            genres=e.genres,
            cast=[CastMember(**c) for c in e.cast],
            backdrop_url=e.backdrop_url,
            poster_url=e.poster_url,
            logo_url=e.logo_url,
        )

    return HeroOut(
        programme_id=p.id,
        channel_name=hero.channel.name,
        title=p.title,
        sub_title=p.sub_title,
        start=local_start,
        stop=local_stop,
        description=p.description,
        categories=p.categories,
        episode_num=p.episode_num,
        year=p.year,
        is_movie=p.is_movie,
        tmdb_connected=hero.tmdb_connected,
        enriching=hero.enriching and enrichment is None,
        enrichment=enrichment,
    )
