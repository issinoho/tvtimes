from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta

import pytest
from app.ingest.xmltv import (
    is_movie,
    maybe_decompress,
    normalize_name,
    parse_time_shift,
    parse_xmltv,
    parse_xmltv_time,
)

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="bbc1.uk">
    <display-name>BBC One</display-name>
    <display-name>BBC 1</display-name>
    <icon src="http://logos/bbc1.png"/>
  </channel>
  <channel id="film4.uk"><display-name>Film4</display-name></channel>
  <programme channel="bbc1.uk" start="20260101190000 +0000" stop="20260101200000 +0000">
    <title>News at Six</title>
    <sub-title>Evening bulletin</sub-title>
    <desc>S1 E1 The day's headlines.</desc>
    <category>News</category>
    <category>Current Affairs</category>
    <episode-num system="onscreen">S1 E1</episode-num>
    <credits><director>Jane Doe</director><director>Sam Roe</director></credits>
  </programme>
  <programme channel="film4.uk" start="20260101210000 +0000" stop="20260101230000 +0000">
    <title>The Big Movie</title>
    <category>Movie</category>
    <date>1994-05-01</date>
  </programme>
</tv>
"""


def test_parse_xmltv_channels_and_programmes() -> None:
    guide = parse_xmltv(SAMPLE)
    assert set(guide.channels) == {"bbc1.uk", "film4.uk"}
    assert guide.channels["bbc1.uk"].display_names == ["BBC One", "BBC 1"]
    assert guide.channels["bbc1.uk"].icon == "http://logos/bbc1.png"

    news = next(p for p in guide.programmes if p.channel_id == "bbc1.uk")
    assert news.title == "News at Six"
    assert news.sub_title == "Evening bulletin"
    assert news.description == "The day's headlines."  # S1 E1 marker stripped
    assert news.categories == ["News", "Current Affairs"]
    assert news.episode_num == "S1 E1"
    assert news.director == "Jane Doe, Sam Roe"
    assert news.start == datetime(2026, 1, 1, 19, tzinfo=UTC)

    movie = next(p for p in guide.programmes if p.channel_id == "film4.uk")
    assert movie.year == "1994"


def test_parse_xmltv_wanted_filter() -> None:
    guide = parse_xmltv(SAMPLE, wanted_channel_ids={"bbc1.uk"})
    assert [p.channel_id for p in guide.programmes] == ["bbc1.uk"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20260716190000", datetime(2026, 7, 16, 19, tzinfo=UTC)),
        ("20260716190000 +0100", datetime(2026, 7, 16, 18, tzinfo=UTC)),
        ("20260716190000 -0500", datetime(2026, 7, 17, 0, tzinfo=UTC)),
    ],
)
def test_parse_xmltv_time(value: str, expected: datetime) -> None:
    assert parse_xmltv_time(value).astimezone(UTC) == expected


def test_parse_xmltv_time_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Invalid XMLTV timestamp"):
        parse_xmltv_time("not-a-time")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+1h30m", timedelta(hours=1, minutes=30)),
        ("-45m", timedelta(minutes=-45)),
        ("30", timedelta(minutes=30)),
        ("", timedelta()),
    ],
)
def test_parse_time_shift(value: str, expected: timedelta) -> None:
    assert parse_time_shift(value) == expected


def test_normalize_name() -> None:
    assert normalize_name("PLUTO - 00s Replay") == "00s replay"
    assert normalize_name("  BBC   One  ⭐") == "bbc one"
    assert normalize_name("24-Hour News") == "24-hour news"


def test_maybe_decompress_roundtrip() -> None:
    raw = b"<tv></tv>"
    assert maybe_decompress(gzip.compress(raw)) == raw
    assert maybe_decompress(raw) == raw


def test_is_movie() -> None:
    assert is_movie(["Movie"])
    assert is_movie([], group_title="Films HD")
    assert not is_movie(["News"], group_title="Entertainment")
