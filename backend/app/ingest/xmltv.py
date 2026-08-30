"""XMLTV parsing and the timezone/clock-shift helpers, ported from
``tvdinner.epg``. Streaming ``iterparse`` keeps memory flat on the very large
feeds (hundreds of MB) some providers serve."""

from __future__ import annotations

import gzip
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO, StringIO
from xml.etree import ElementTree

_XMLTV_TIME_RE = re.compile(
    r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*(?:([+-]\d{2})(\d{2}))?$"
)
_SHIFT_RE = re.compile(r"^([+-]?)(?:(\d+)h)?(?:(\d+)m)?$", re.IGNORECASE)
_NAME_SOURCE_TAG_RE = re.compile(r"^[A-Za-z0-9]+\s+-\s+")
_EPISODE_MARKER_RE = re.compile(r"^S\d+\s*E\d+\s*", re.IGNORECASE)
FEED_SUFFIX_RE = re.compile(r"@[^@]+$")

_MOVIE_KEYWORDS = ("movie", "film", "cinema")


# --- name normalisation (programme <-> channel matching) ---------------------


def _strip_trailing_decoration(text: str) -> str:
    while text and (text[-1].isspace() or unicodedata.category(text[-1]).startswith("S")):
        text = text[:-1]
    return text


def normalize_name(name: str) -> str:
    text = _NAME_SOURCE_TAG_RE.sub("", name.strip())
    text = _strip_trailing_decoration(text)
    return re.sub(r"\s+", " ", text).strip().lower()


# --- time helpers -----------------------------------------------------------


def parse_xmltv_time(value: str) -> datetime:
    """``20260716190000 +0100`` -> aware datetime. No offset means UTC."""
    match = _XMLTV_TIME_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid XMLTV timestamp: {value!r}")
    y, mo, d, h, mi, s, off_h, off_m = match.groups()
    if off_h is None:
        tz: timezone = UTC
    else:
        sign = -1 if off_h.startswith("-") else 1
        tz = timezone(sign * timedelta(hours=abs(int(off_h)), minutes=int(off_m)))
    return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=tz)


def parse_time_shift(value: str) -> timedelta:
    """``+1h30m`` / ``-45m`` / bare integer minutes -> timedelta."""
    text = value.strip()
    if not text:
        return timedelta()
    match = _SHIFT_RE.match(text)
    if match and (match.group(2) or match.group(3)):
        sign = -1 if match.group(1) == "-" else 1
        return sign * timedelta(hours=int(match.group(2) or 0), minutes=int(match.group(3) or 0))
    try:
        return timedelta(minutes=int(text))
    except ValueError:
        raise ValueError(
            f"Invalid time shift: {value!r} (e.g. '+1h30m', '-45m', or minutes)"
        ) from None


def _release_year(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"(\d{4})", value.strip())
    return match.group(1) if match else None


def _strip_episode_marker(description: str) -> str:
    return _EPISODE_MARKER_RE.sub("", description)


def is_movie(categories: list[str], group_title: str | None = None) -> bool:
    haystack = " ".join(categories).lower()
    if group_title:
        haystack += " " + group_title.lower()
    return any(k in haystack for k in _MOVIE_KEYWORDS)


# --- parsed model ---------------------------------------------------------------


@dataclass(slots=True)
class XmltvChannel:
    id: str
    display_names: list[str] = field(default_factory=list)
    icon: str | None = None


@dataclass(slots=True)
class XmltvProgramme:
    channel_id: str
    start: datetime
    stop: datetime
    title: str
    sub_title: str | None = None
    description: str | None = None
    categories: list[str] = field(default_factory=list)
    icon_url: str | None = None
    year: str | None = None
    director: str | None = None
    episode_num: str | None = None


@dataclass(slots=True)
class ParsedGuide:
    channels: dict[str, XmltvChannel] = field(default_factory=dict)
    programmes: list[XmltvProgramme] = field(default_factory=list)


def maybe_decompress(data: bytes) -> bytes:
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except OSError:
            return data
    return data


def _text(elem: ElementTree.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    return elem.text.strip() or None


def _episode_num(elem: ElementTree.Element) -> str | None:
    """Prefer a human 'onscreen' value, else the raw xmltv_ns triplet."""
    onscreen = raw = None
    for en in elem.findall("episode-num"):
        system = (en.get("system") or "").lower()
        value = (en.text or "").strip()
        if not value:
            continue
        if system == "onscreen":
            onscreen = value
        elif system in ("", "xmltv_ns"):
            raw = value
    return onscreen or raw


def parse_xmltv(data: bytes | str, wanted_channel_ids: set[str] | None = None) -> ParsedGuide:
    source = BytesIO(data) if isinstance(data, bytes) else StringIO(data)
    guide = ParsedGuide()
    resolved_wanted: set[str] = set()

    context = iter(ElementTree.iterparse(source, events=("start", "end")))
    _, root = next(context)

    for event, elem in context:
        if event != "end":
            continue

        if elem.tag == "channel":
            channel_id = elem.get("id", "")
            if channel_id:
                names = [
                    el.text.strip()
                    for el in elem.findall("display-name")
                    if el.text and el.text.strip()
                ]
                if wanted_channel_ids is not None and (
                    channel_id in wanted_channel_ids
                    or any(normalize_name(n) in wanted_channel_ids for n in names)
                ):
                    resolved_wanted.add(channel_id)
                icon_el = elem.find("icon")
                icon = icon_el.get("src") if icon_el is not None else None
                existing = guide.channels.get(channel_id)
                if existing is None:
                    guide.channels[channel_id] = XmltvChannel(channel_id, names, icon)
                else:
                    existing.display_names.extend(
                        n for n in names if n not in existing.display_names
                    )
                    existing.icon = existing.icon or icon

        elif elem.tag == "programme":
            channel_id = elem.get("channel", "")
            start_raw, stop_raw = elem.get("start"), elem.get("stop")
            start = stop = None
            if channel_id and start_raw and stop_raw:
                try:
                    start, stop = parse_xmltv_time(start_raw), parse_xmltv_time(stop_raw)
                except ValueError:
                    start = stop = None
            wanted_ok = wanted_channel_ids is None or channel_id in resolved_wanted
            if start is not None and stop is not None and wanted_ok:
                categories = [
                    c.text.strip() for c in elem.findall("category") if c.text and c.text.strip()
                ]
                credits_el = elem.find("credits")
                directors = (
                    [
                        d.text.strip()
                        for d in credits_el.findall("director")
                        if d.text and d.text.strip()
                    ]
                    if credits_el is not None
                    else []
                )
                desc = _text(elem.find("desc"))
                guide.programmes.append(
                    XmltvProgramme(
                        channel_id=channel_id,
                        start=start,
                        stop=stop,
                        title=_text(elem.find("title")) or "",
                        sub_title=_text(elem.find("sub-title")),
                        description=_strip_episode_marker(desc) if desc else None,
                        categories=categories,
                        icon_url=(
                            elem.find("icon").get("src") if elem.find("icon") is not None else None
                        ),
                        year=_release_year(_text(elem.find("date"))),
                        director=", ".join(directors) or None,
                        episode_num=_episode_num(elem),
                    )
                )
        else:
            continue

        elem.clear()
        root.clear()

    guide.programmes.sort(key=lambda p: (p.channel_id, p.start))
    return guide
