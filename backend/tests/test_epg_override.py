"""Matching a channel to guide data it can't find on its own.

Modelled on a real case: an HDHomeRun tuner numbers BBC One Scotland HD
101, while the guide carries that programming under 1. The tuner's
ext_id *is* the channel number, the names differ too ("BBC 1 Scot HD" vs
"BBC ONE Scot"), so nothing matches and the HD row sits empty while the
SD one is full.
"""

from __future__ import annotations

import uuid

from app.db import get_sessionmaker
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import epg as svc
from app.services import sources as src_svc


async def _seed() -> dict[str, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="Europe/London")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.hdhomerun,
            display_name="HDHomeRun",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        sd = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="1",
            ext_id="1",
            name="BBC ONE Scot",
            tvg_name="BBC ONE Scot",
            stream_ref_encrypted="x",
        )
        hd = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="101",
            ext_id="101",
            name="BBC 1 Scot HD",
            tvg_name="BBC 1 Scot HD",
            stream_ref_encrypted="x",
        )
        session.add_all([sd, hd])
        await session.commit()
        return {"tenant": tenant.id, "sd": sd.id, "hd": hd.id}


async def _index(tenant_id: uuid.UUID) -> dict[str, list[uuid.UUID]]:
    async with get_sessionmaker()() as session:
        return await svc._channel_index(session, tenant_id)


async def _set_override(channel_id: uuid.UUID, value: str | None) -> None:
    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, channel_id)
        assert channel is not None
        channel.epg_override_id = value
        await session.commit()


async def test_without_an_override_the_hd_variant_matches_nothing_the_guide_has(
    db_schema: None,
) -> None:
    ids = await _seed()
    index = await _index(ids["tenant"])
    # The guide keys its Scottish programming "1". The HD channel is only
    # reachable under 101 and its own name, so it never sees any of it.
    assert index["1"] == [ids["sd"]]
    assert index["101"] == [ids["hd"]]


async def test_an_override_makes_the_hd_variant_share_the_sd_channels_guide(
    db_schema: None,
) -> None:
    ids = await _seed()
    await _set_override(ids["hd"], "1")
    index = await _index(ids["tenant"])
    # Both channels now answer to "1" -- _channel_index already fans a key out
    # to several channels, and each gets its own copy of the programmes.
    assert index["1"] == [ids["sd"], ids["hd"]]


async def test_an_override_replaces_the_channels_own_keys(db_schema: None) -> None:
    ids = await _seed()
    await _set_override(ids["hd"], "1")
    index = await _index(ids["tenant"])
    # Exclusive on purpose: leaving the old keys in place would let a feed
    # that happens to carry 101 too win back the match that was overridden.
    assert "101" not in index
    assert "bbc 1 scot hd" not in index


async def test_clearing_an_override_restores_automatic_matching(db_schema: None) -> None:
    ids = await _seed()
    await _set_override(ids["hd"], "1")
    await _set_override(ids["hd"], None)
    index = await _index(ids["tenant"])
    assert index["101"] == [ids["hd"]]
    assert index["1"] == [ids["sd"]]


async def test_an_override_is_matched_case_insensitively(db_schema: None) -> None:
    # tvg-id casing is inconsistent between feeds; the automatic keys already
    # lower-case, and a hand-typed override shouldn't behave differently.
    ids = await _seed()
    await _set_override(ids["hd"], "  BBC.One.Scotland  ")
    index = await _index(ids["tenant"])
    assert index["bbc.one.scotland"] == [ids["hd"]]


async def test_patch_sets_and_clears_the_override_without_touching_the_shift(
    db_schema: None,
) -> None:
    # The endpoint is patch-style: each field is independent, so setting a
    # guide key must not reset a clock shift someone tuned earlier.
    ids = await _seed()
    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, ids["hd"])
        assert channel is not None
        channel.clock_shift_seconds = 3600
        await session.commit()

    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, ids["hd"])
        assert channel is not None
        await src_svc.set_channel_epg_override(session, channel, epg_override_id="  1  ")
        await session.commit()

    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, ids["hd"])
        assert channel is not None
        assert channel.epg_override_id == "1"  # trimmed
        assert channel.clock_shift_seconds == 3600  # untouched

        await src_svc.set_channel_epg_override(session, channel, epg_override_id="   ")
        await session.commit()

    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, ids["hd"])
        assert channel is not None
        assert channel.epg_override_id is None  # blank clears it
