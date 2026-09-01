"""M3U / XMLTV export feeds and per-channel stream resolution."""

from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlparse
from zoneinfo import ZoneInfo

import jwt
import pytest
from app.auth import tokens
from app.auth.crypto import encrypt
from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import exports as svc
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

XTREAM_CONFIG = {
    "server_url": "http://provider.example:8080",
    "username": "user1",
    "password": "pass1",
    "output": "ts",
}

# A programme inside the export window (now-1d … now+14d), at a fixed wall time.
PROG_START = (datetime.now(UTC) + timedelta(days=1)).replace(
    hour=19, minute=0, second=0, microsecond=0
)


async def _seed() -> dict[str, uuid.UUID]:
    """A tenant with an m3u source (2 channels, one on a disabled source),
    an xtream source (1 channel) and a stalker source (1 channel), plus one
    programme on the first m3u channel."""
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="Europe/London")
        session.add(tenant)
        await session.flush()

        m3u = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="Playlist",
            config_encrypted="x",
            timezone_override="America/New_York",
            last_status=SourceStatus.ok,
            sort_rank=0,
        )
        xtream = Source(
            tenant_id=tenant.id,
            kind=SourceKind.xtream,
            display_name="Xtream",
            config_encrypted=encrypt(json.dumps(XTREAM_CONFIG)),
            last_status=SourceStatus.ok,
            sort_rank=1,
        )
        stalker = Source(
            tenant_id=tenant.id,
            kind=SourceKind.stalker,
            display_name="Portal",
            config_encrypted="x",
            last_status=SourceStatus.ok,
            sort_rank=2,
        )
        disabled = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="Off",
            config_encrypted="x",
            last_status=SourceStatus.ok,
            enabled=False,
            sort_rank=3,
        )
        session.add_all([m3u, xtream, stalker, disabled])
        await session.flush()

        ch_m3u = Channel(
            tenant_id=tenant.id,
            source_id=m3u.id,
            dedupe_key="m1",
            ext_id="bbc.uk",
            name="BBC One",
            tvg_name="BBC One HD",
            logo_url="http://logos.example/bbc.png",
            group_title="Entertainment",
            number=1,
            stream_ref_encrypted=encrypt("http://provider.example/bbc.ts"),
            clock_shift_seconds=3600,
        )
        ch_xtream = Channel(
            tenant_id=tenant.id,
            source_id=xtream.id,
            dedupe_key="x1",
            name="Sky Sports",
            stream_ref_encrypted=encrypt("55555"),
        )
        ch_stalker = Channel(
            tenant_id=tenant.id,
            source_id=stalker.id,
            dedupe_key="s1",
            name="Portal Chan",
            stream_ref_encrypted=encrypt("ffff0000"),
        )
        ch_off = Channel(
            tenant_id=tenant.id,
            source_id=disabled.id,
            dedupe_key="d1",
            name="Hidden",
            stream_ref_encrypted=encrypt("http://x/hidden.ts"),
        )
        epg = EpgSource(tenant_id=tenant.id, source_id=m3u.id, url="http://x")
        session.add_all([ch_m3u, ch_xtream, ch_stalker, ch_off, epg])
        await session.flush()

        session.add(
            Programme(
                tenant_id=tenant.id,
                channel_id=ch_m3u.id,
                epg_source_id=epg.id,
                start_utc=PROG_START,
                stop_utc=PROG_START + timedelta(hours=1),
                title="The Nine O'Clock News",
                categories=["News"],
            )
        )
        await session.commit()
        return {
            "tenant": tenant.id,
            "ch_m3u": ch_m3u.id,
            "ch_xtream": ch_xtream.id,
            "ch_stalker": ch_stalker.id,
            "ch_off": ch_off.id,
        }


# --- service-level -----------------------------------------------------------


async def test_token_roundtrip_and_rotation(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, ids["tenant"])
        assert tenant is not None
        first = await svc.generate_token(session, tenant)
        await session.commit()

    async with get_sessionmaker()() as session:
        assert (await svc.tenant_for_token(session, first)) is not None
        assert (await svc.tenant_for_token(session, "nope")) is None
        assert (await svc.tenant_for_token(session, "")) is None
        tenant = await session.get(Tenant, ids["tenant"])
        assert tenant is not None
        second = await svc.generate_token(session, tenant)
        await session.commit()

    assert second != first
    async with get_sessionmaker()() as session:
        assert (await svc.tenant_for_token(session, first)) is None
        assert (await svc.tenant_for_token(session, second)) is not None


async def test_render_m3u_shape(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, ids["tenant"])
        assert tenant is not None
        body = await svc.render_m3u(session, tenant, base_url="https://tv.example", token="TOK")

    lines = body.splitlines()
    assert lines[0] == '#EXTM3U url-tvg="https://tv.example/api/exports/epg.xml?token=TOK"'
    extinfs = [ln for ln in lines if ln.startswith("#EXTINF")]
    # m3u + xtream + stalker channels, but not the one on the disabled source.
    assert len(extinfs) == 3
    assert 'tvg-id="Hidden"' not in body and "Hidden" not in body
    # channel is keyed by our UUID, not the upstream tvg-id.
    assert f'tvg-id="{ids["ch_m3u"]}"' in body
    assert "bbc.uk" not in body
    assert 'tvg-logo="http://logos.example/bbc.png"' in body
    assert 'tvg-chno="1"' in body
    assert 'group-title="Entertainment"' in body
    assert f"https://tv.example/api/exports/stream/{ids['ch_m3u']}?token=TOK" in body


async def test_render_xmltv_applies_timezone_and_shift(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        tenant = await session.get(Tenant, ids["tenant"])
        assert tenant is not None
        chunks = [c async for c in svc.render_xmltv(session, tenant)]
    doc = "".join(chunks)
    root = ET.fromstring(doc)

    assert root.tag == "tv"
    channel_ids = {c.get("id") for c in root.findall("channel")}
    assert str(ids["ch_m3u"]) in channel_ids
    assert str(ids["ch_off"]) not in channel_ids

    progs = root.findall("programme")
    assert len(progs) == 1
    p = progs[0]
    assert p.get("channel") == str(ids["ch_m3u"])
    # source tz override (America/New_York) + 1h channel clock shift, both applied.
    expected = (PROG_START + timedelta(hours=1)).astimezone(ZoneInfo("America/New_York"))
    assert p.get("start") == expected.strftime("%Y%m%d%H%M%S %z")
    start = p.get("start")
    assert start is not None and start.endswith((" -0400", " -0500"))  # ET, never +0000
    assert p.findtext("title") == "The Nine O'Clock News"
    assert p.findtext("category") == "News"


async def test_resolve_stream_per_kind(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        ch_m3u = await session.get(Channel, ids["ch_m3u"])
        ch_xtream = await session.get(Channel, ids["ch_xtream"])
        ch_stalker = await session.get(Channel, ids["ch_stalker"])
        assert ch_m3u and ch_xtream and ch_stalker
        src_m3u = await session.get(Source, ch_m3u.source_id)
        src_xtream = await session.get(Source, ch_xtream.source_id)
        src_stalker = await session.get(Source, ch_stalker.source_id)

    assert svc.resolve_stream(ch_m3u, src_m3u) == "http://provider.example/bbc.ts"
    assert (
        svc.resolve_stream(ch_xtream, src_xtream)
        == "http://provider.example:8080/live/user1/pass1/55555.ts"
    )
    with pytest.raises(svc.StreamUnavailable):
        svc.resolve_stream(ch_stalker, src_stalker)


# --- API --------------------------------------------------------------------


async def test_exports_require_token(app_client: AsyncClient) -> None:
    for path in ("/api/exports/playlist.m3u", "/api/exports/epg.xml"):
        resp = await app_client.get(path)
        assert resp.status_code == 401, resp.text
        resp = await app_client.get(path, params={"token": "bogus"})
        assert resp.status_code == 401, resp.text


async def test_account_export_token_lifecycle(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    access = await login(app_client)
    h = auth_header(access)

    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert me["export_token_set_at"] is None

    created = await app_client.post("/api/account/export-token", headers=h)
    assert created.status_code == 200, created.text
    payload = created.json()
    token = payload["token"]
    assert payload["playlist_url"].endswith(f"/api/exports/playlist.m3u?token={token}")
    assert payload["epg_url"].endswith(f"/api/exports/epg.xml?token={token}")

    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert me["export_token_set_at"] is not None

    # Both feeds are now reachable with that token.
    feed = await app_client.get("/api/exports/playlist.m3u", params={"token": token})
    assert feed.status_code == 200, feed.text
    assert feed.text.startswith("#EXTM3U")
    assert feed.headers["content-type"].startswith("application/x-mpegurl")

    epg = await app_client.get("/api/exports/epg.xml", params={"token": token})
    assert epg.status_code == 200, epg.text
    assert epg.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(epg.text)
    assert root.tag == "tv"

    # Rotating invalidates the old token.
    rotated = (await app_client.post("/api/account/export-token", headers=h)).json()
    assert rotated["token"] != token
    assert (
        await app_client.get("/api/exports/playlist.m3u", params={"token": token})
    ).status_code == 401
    assert (
        await app_client.get("/api/exports/playlist.m3u", params={"token": rotated["token"]})
    ).status_code == 200

    # Revoking kills it entirely.
    assert (await app_client.delete("/api/account/export-token", headers=h)).status_code == 200
    assert (
        await app_client.get("/api/exports/playlist.m3u", params={"token": rotated["token"]})
    ).status_code == 401
    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert me["export_token_set_at"] is None


async def test_stream_redirects(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    access = await login(app_client)
    h = auth_header(access)
    token = (await app_client.post("/api/account/export-token", headers=h)).json()["token"]

    # Seed sources/channels directly for the just-created tenant.
    me = (await app_client.get("/api/account/me", headers=h)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    async with get_sessionmaker()() as session:
        src = Source(
            tenant_id=tenant_id,
            kind=SourceKind.m3u,
            display_name="P",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(src)
        await session.flush()
        ch = Channel(
            tenant_id=tenant_id,
            source_id=src.id,
            dedupe_key="c",
            name="C",
            stream_ref_encrypted=encrypt("http://upstream.example/c.ts"),
        )
        session.add(ch)
        await session.flush()
        channel_id = ch.id
        await session.commit()

    resp = await app_client.get(f"/api/exports/stream/{channel_id}", params={"token": token})
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://upstream.example/c.ts"

    missing = await app_client.get(f"/api/exports/stream/{uuid.uuid4()}", params={"token": token})
    assert missing.status_code == 404


# --- "Play externally" hand-off -------------------------------------------------


def test_play_token_roundtrip() -> None:
    cid, tid = uuid.uuid4(), uuid.uuid4()
    assert tokens.decode_play_token(tokens.issue_play_token(cid, tid)) == (cid, tid)


def test_play_token_rejects_other_types_and_junk() -> None:
    with pytest.raises(jwt.PyJWTError):
        tokens.decode_play_token(tokens.issue_mfa_token(uuid.uuid4()))
    with pytest.raises(jwt.PyJWTError):
        tokens.decode_play_token("not-a-jwt")


def test_play_token_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tokens, "PLAY_TOKEN_TTL", timedelta(seconds=-1))
    tok = tokens.issue_play_token(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(jwt.ExpiredSignatureError):
        tokens.decode_play_token(tok)


def test_play_m3u_filename_is_safe() -> None:
    class _C:
        name = 'BBC One "HD" / North\tπ'

    # quotes / slashes / tabs / non-ascii stripped, spaces collapsed
    assert svc.play_m3u_filename(_C()) == "BBC One HD North.m3u"  # type: ignore[arg-type]
    assert svc.play_m3u_filename(type("X", (), {"name": "  \t "})()) == "channel.m3u"


async def _play_setup(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    *,
    email: str = "sam@example.com",
) -> tuple[dict[str, str], dict[str, uuid.UUID]]:
    await register_and_verify(app_client, captured_emails, email=email, display_name="Sam")
    h = auth_header(await login(app_client, email=email))
    me = (await app_client.get("/api/account/me", headers=h)).json()
    tenant_id = uuid.UUID(me["tenant_id"])
    async with get_sessionmaker()() as session:
        m3u = Source(
            tenant_id=tenant_id,
            kind=SourceKind.m3u,
            display_name="P",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        portal = Source(
            tenant_id=tenant_id,
            kind=SourceKind.stalker,
            display_name="Portal",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add_all([m3u, portal])
        await session.flush()
        ch = Channel(
            tenant_id=tenant_id,
            source_id=m3u.id,
            dedupe_key="c",
            name="BBC One HD",
            tvg_name="BBC One HD",
            logo_url="http://logos.example/bbc.png",
            number=1,
            group_title="Ents",
            stream_ref_encrypted=encrypt("http://provider.example/bbc.ts"),
        )
        ch2 = Channel(
            tenant_id=tenant_id,
            source_id=m3u.id,
            dedupe_key="c2",
            name="ITV1 HD",
            stream_ref_encrypted=encrypt("http://provider.example/itv.ts"),
        )
        ch_stalker = Channel(
            tenant_id=tenant_id,
            source_id=portal.id,
            dedupe_key="s",
            name="Portal Chan",
            stream_ref_encrypted=encrypt("ffff"),
        )
        epg = EpgSource(tenant_id=tenant_id, source_id=m3u.id, url="http://x")
        session.add_all([ch, ch2, ch_stalker, epg])
        await session.flush()
        session.add_all(
            [
                Programme(
                    tenant_id=tenant_id,
                    channel_id=ch.id,
                    epg_source_id=epg.id,
                    start_utc=PROG_START,
                    stop_utc=PROG_START + timedelta(hours=1),
                    title="Match of the Day",
                ),
                Programme(
                    tenant_id=tenant_id,
                    channel_id=ch2.id,
                    epg_source_id=epg.id,
                    start_utc=PROG_START,
                    stop_utc=PROG_START + timedelta(hours=1),
                    title="Coronation Street",
                ),
            ]
        )
        await session.commit()
        return h, {"m3u": ch.id, "m3u2": ch2.id, "stalker": ch_stalker.id}


def _rel(url: str) -> tuple[str, dict[str, str]]:
    """Absolute play URL -> (path, query dict) for the ASGI test client."""
    u = urlparse(url)
    return u.path, dict(parse_qsl(u.query))


async def test_play_link_requires_auth(app_client: AsyncClient) -> None:
    resp = await app_client.post(f"/api/channels/{uuid.uuid4()}/play-link")
    assert resp.status_code == 401


async def test_play_link_mint_and_serve_m3u(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    h, ids = await _play_setup(app_client, captured_emails)
    minted = await app_client.post(f"/api/channels/{ids['m3u']}/play-link", headers=h)
    assert minted.status_code == 200, minted.text
    body = minted.json()
    assert body["expires_in"] == 86400
    assert f"/api/exports/play/{ids['m3u']}/playlist.m3u?ticket=" in body["m3u_url"]
    assert f"/api/exports/play/{ids['m3u']}/stream?ticket=" in body["stream_url"]

    path, params = _rel(body["m3u_url"])
    m3u = await app_client.get(path, params=params)
    assert m3u.status_code == 200, m3u.text
    assert m3u.headers["content-type"].startswith("audio/x-mpegurl")
    cd = m3u.headers["content-disposition"]
    assert "attachment" in cd and cd.rstrip().endswith('.m3u"')
    lines = m3u.text.splitlines()
    assert lines[0].startswith("#EXTM3U ") and 'url-tvg="' in lines[0]
    assert f"/api/exports/play/{ids['m3u']}/epg.xml?ticket=" in lines[0]
    assert lines[1].startswith("#EXTINF:-1 ") and f'tvg-id="{ids["m3u"]}"' in lines[1]
    assert lines[2] == body["stream_url"]
    assert "provider.example" not in m3u.text  # upstream URL never in the file

    # ...and that url-tvg serves this one channel's guide, nothing else.
    tvg_url = lines[0].split('url-tvg="', 1)[1].split('"', 1)[0]
    ep_path, ep_params = _rel(tvg_url)
    epg = await app_client.get(ep_path, params=ep_params)
    assert epg.status_code == 200, epg.text
    assert epg.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(epg.text)
    assert [c.get("id") for c in root.findall("channel")] == [str(ids["m3u"])]
    assert {p.get("channel") for p in root.findall("programme")} == {str(ids["m3u"])}
    assert "Match of the Day" in epg.text
    assert "Coronation Street" not in epg.text  # the other channel's programme
    assert str(ids["m3u2"]) not in epg.text


async def test_play_epg_xml_rejects_a_bad_ticket(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    _h, ids = await _play_setup(app_client, captured_emails)
    for params in ({}, {"ticket": "garbage"}):
        resp = await app_client.get(f"/api/exports/play/{ids['m3u']}/epg.xml", params=params)
        assert resp.status_code == 401


async def test_play_stream_redirects(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    h, ids = await _play_setup(app_client, captured_emails)
    body = (await app_client.post(f"/api/channels/{ids['m3u']}/play-link", headers=h)).json()
    path, params = _rel(body["stream_url"])
    resp = await app_client.get(path, params=params)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://provider.example/bbc.ts"


async def test_play_link_stalker_501(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    h, ids = await _play_setup(app_client, captured_emails)
    resp = await app_client.post(f"/api/channels/{ids['stalker']}/play-link", headers=h)
    assert resp.status_code == 501


async def test_play_link_unknown_and_cross_tenant_404(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    h, ids = await _play_setup(app_client, captured_emails)
    assert (
        await app_client.post(f"/api/channels/{uuid.uuid4()}/play-link", headers=h)
    ).status_code == 404

    h2, _ = await _play_setup(app_client, captured_emails, email="other@example.com")
    assert (
        await app_client.post(f"/api/channels/{ids['m3u']}/play-link", headers=h2)
    ).status_code == 404


async def test_play_ticket_invalid_or_wrong_channel_401(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    h, ids = await _play_setup(app_client, captured_emails)
    for params in ({}, {"ticket": "garbage"}):
        resp = await app_client.get(f"/api/exports/play/{ids['m3u']}/playlist.m3u", params=params)
        assert resp.status_code == 401

    body = (await app_client.post(f"/api/channels/{ids['m3u']}/play-link", headers=h)).json()
    _p, params = _rel(body["stream_url"])
    # channel m3u's ticket used on the stalker channel's path
    resp = await app_client.get(f"/api/exports/play/{ids['stalker']}/stream", params=params)
    assert resp.status_code == 401
