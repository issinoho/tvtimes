from __future__ import annotations

from app.ingest.m3u import parse_m3u
from app.ingest.models import Channel
from app.ingest.redact import redact_mac, redact_resource_url, source_config_summary
from app.ingest.stalker import StalkerCreds, parse_stalker_url, valid_mac
from app.ingest.xtream import XtreamCreds, build_live_url, parse_xtream_url, xtream_epg_url

SAMPLE_M3U = """#EXTM3U x-tvg-url="http://epg.example.com/guide.xml"
#EXTINF:-1 tvg-id="news.us" tvg-name="News" tvg-logo="http://logo/n.png" group-title="News",News HD
http://stream.example.com/news.m3u8
#EXTINF:-1 tvg-id="" group-title="Movies",Movie Channel, Extra
http://stream.example.com/movies.m3u8
"""


def test_parse_m3u_header_and_channels() -> None:
    pl = parse_m3u(SAMPLE_M3U)
    assert pl.epg_url == "http://epg.example.com/guide.xml"
    assert len(pl.channels) == 2
    first = pl.channels[0]
    assert first.name == "News HD"
    assert first.stream_ref == "http://stream.example.com/news.m3u8"
    assert first.tvg_id == "news.us"
    assert first.is_hd is True
    # a name containing a comma survives; empty tvg-id becomes None
    assert pl.channels[1].name == "Movie Channel, Extra"
    assert pl.channels[1].tvg_id is None


def test_parse_m3u_empty() -> None:
    pl = parse_m3u("#EXTM3U\n")
    assert pl.channels == []


def test_channel_groups_and_hd() -> None:
    ch = Channel(name="X", stream_ref="u", group_title="Movies;Series")
    assert ch.groups == ["Movies", "Series"]
    assert not Channel(name="HDNet", stream_ref="u").is_hd


def test_parse_xtream_url_roundtrip() -> None:
    creds = parse_xtream_url("xtreams://user%40x:p%40ss@panel.example.com:8080?output=m3u8")
    assert creds == XtreamCreds(
        base_url="https://panel.example.com:8080",
        username="user@x",
        password="p@ss",
        output="m3u8",
    )
    assert xtream_epg_url(creds).startswith("https://panel.example.com:8080/xmltv.php")
    assert build_live_url(creds, "42") == (
        "https://panel.example.com:8080/live/user@x/p@ss/42.m3u8"
    )


def test_parse_xtream_url_rejects_missing_creds() -> None:
    assert parse_xtream_url("xtream://panel.example.com") is None
    assert parse_xtream_url("http://not-xtream") is None


def test_parse_stalker_url() -> None:
    creds = parse_stalker_url(
        "stalker://portal.example.com:80/stalker_portal/c/?mac=00:1A:79:AA:BB:CC"
    )
    assert creds is not None
    assert creds.base_url == "http://portal.example.com:80"
    assert creds.portal_path == "/stalker_portal/c/portal.php"
    assert creds.mac == "00:1A:79:AA:BB:CC"
    assert parse_stalker_url("stalker://portal.example.com/c/?mac=nope") is None
    assert valid_mac("00:1a:79:aa:bb:cc")


def test_stalker_creds_from_config_appends_portal_php() -> None:
    creds = StalkerCreds.from_config(
        {"portal_url": "http://p.example.com/c", "mac": "00:1A:79:AA:BB:CC"}
    )
    assert creds.portal_path == "/c/portal.php"


def test_redactors() -> None:
    assert redact_mac("00:1A:79:AA:BB:CC") == "00:1A:**:**:**:**"
    masked = redact_resource_url("http://h/live/xtreamuser/secretpass/5.ts?password=hunter2")
    assert "secretpass" not in masked
    assert "xtreamuser" not in masked  # the username path segment is masked too
    assert "hunter2" not in masked
    assert redact_resource_url("http://user:pw@h/x").count("pw") == 0


def test_redactors_cover_extra_query_creds() -> None:
    # tvtimes' own play links use ?ticket=<jwt>; also auth / access_token / sig
    masked = redact_resource_url(
        "https://h/exports/play/c/stream?ticket=eyJhbGciOiJFZERTQSJ9.body.sig"
        "&access_token=SEKRET123&auth=abcdef&type=m3u"
    )
    assert "body.sig" not in masked and "SEKRET123" not in masked and "abcdef" not in masked
    assert "type=m3u" in masked  # non-credential params are untouched


def test_source_config_summary_hides_credentials() -> None:
    assert source_config_summary("m3u", {"url": "http://h.example.com/list.m3u"}) == (
        "http://h.example.com/list.m3u"
    )
    xt = source_config_summary(
        "xtream",
        {"server_url": "http://h.example.com:8080", "username": "bob", "password": "s3cret"},
    )
    assert "s3cret" not in xt and "h.example.com" in xt
    st = source_config_summary(
        "stalker", {"portal_url": "http://h.example.com/c/portal.php", "mac": "00:1A:79:AA:BB:CC"}
    )
    assert "AA:BB:CC" not in st
