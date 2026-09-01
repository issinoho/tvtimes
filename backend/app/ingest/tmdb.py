"""TMDB search + detail fetching, adapted from ``tvdinner.tmdb`` /
``tvdinner.movietitle``.

Design rules kept from tvdinner:
  * never send ``year`` as a hard search filter — pick the best candidate
    client-side after a title-only search
  * strip an exact ``(YYYY)`` suffix before searching
  * when the source has no year at all, fall back to one embedded as a
    trailing "(YYYY)" on the title, so a same-titled remake doesn't win on
    TMDB's popularity sort (e.g. "The Longest Yard (1974)" vs. the 2005 remake)
  * prefer a textless, widest backdrop and an English, non-SVG, widest logo
  * a genuine no-match is cacheable; a request failure is not

Upgrade over tvdinner: one ``/{movie|tv}/{id}?append_to_response=credits,images``
call gets genres, cast, crew and images together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

_BASE = "https://api.themoviedb.org/3"
_IMG = "https://image.tmdb.org/t/p"
BACKDROP = f"{_IMG}/w1280"
POSTER = f"{_IMG}/w500"
LOGO = f"{_IMG}/w500"

_YEAR_RE = re.compile(r"[(\[]?((?:19|20)\d{2})[)\]]?")
_TRAILING_YEAR_RE = re.compile(r"\s*[(\[]((?:19|20)\d{2})[)\]]\s*$")
_SEGMENT_SPLIT_RE = re.compile(r"\s[-|·–—]\s")  # noqa: RUF001 - en/em dash separators are intentional
_STRIP = " -()[]"
_MAX_CAST = 8


class TmdbError(Exception):
    """A request/parse failure — the caller must NOT cache a negative."""


# --- title parsing (ported from movietitle.py) ------------------------------


def guess_title_year(text: str) -> tuple[str, str | None]:
    match = _YEAR_RE.search(text)
    if match is None:
        return text.strip(), None
    before = text[: match.start()].strip(_STRIP)
    after = text[match.end() :].strip(_STRIP)
    return (before or after or text.strip(_STRIP)), match.group(1)


def title_search_candidates(title: str) -> list[str]:
    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(title) if s.strip()]
    candidates = [segments[0], title] if len(segments) > 1 else [title]
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def strip_embedded_year(title: str, year: str | None) -> str:
    if year and title.endswith(f"({year})"):
        return title[: -(len(year) + 3)].rstrip()
    return title


def guess_trailing_year(title: str) -> tuple[str, str | None]:
    """A year the source embedded as a trailing "(YYYY)"/"[YYYY]" on the
    title, e.g. "The Longest Yard (1974)" — the fallback used when the feed's
    own ``<date>`` is missing, so a same-titled remake doesn't win on TMDB's
    popularity-sorted search.

    Deliberately narrow: the year must be the last, parenthesised token, so a
    title that's bare digits ("1917") or ends in an unparenthesised one
    ("Blade Runner 2049") has nothing to match and is returned unchanged.
    """
    match = _TRAILING_YEAR_RE.search(title)
    if not match:
        return title, None
    stripped = title[: match.start()].rstrip()
    return (stripped or title), match.group(1)


# --- fetching -------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


async def _get(client: httpx.AsyncClient, path: str, token: str, **params: str) -> Any:
    try:
        resp = await client.get(
            f"{_BASE}{path}", params=params, headers=_headers(token), timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TmdbError(f"TMDB {path} failed: {exc.__class__.__name__}") from exc


async def search(
    client: httpx.AsyncClient, media_type: str, title: str, year: str | None, token: str
) -> dict[str, Any] | None:
    """Best result dict, or None for a genuine no-match. Raises TmdbError on a
    request failure."""
    if not year:
        title, year = guess_trailing_year(title)
    payload = await _get(
        client, f"/search/{media_type}", token, query=strip_embedded_year(title, year)
    )
    results = payload.get("results") or []
    if not results:
        return None
    date_field = "release_date" if media_type == "movie" else "first_air_date"
    best: dict[str, Any] = results[0]
    if year:
        for r in results:
            if str(r.get(date_field, ""))[:4] == year:
                best = r
                break
    return best


async def details(
    client: httpx.AsyncClient, media_type: str, tmdb_id: int, token: str
) -> dict[str, Any]:
    data: dict[str, Any] = await _get(
        client, f"/{media_type}/{tmdb_id}", token, append_to_response="credits,images"
    )
    return data


def _best_backdrop(images: dict[str, Any], fallback: str | None) -> str | None:
    backdrops = images.get("backdrops") or []
    if not backdrops:
        return fallback
    textless = [b for b in backdrops if b.get("iso_639_1") is None]
    best = max(textless or backdrops, key=lambda b: b.get("width") or 0)
    return best.get("file_path") or fallback


def _best_logo(images: dict[str, Any]) -> str | None:
    logos = [
        logo
        for logo in (images.get("logos") or [])
        if not str(logo.get("file_path")).endswith(".svg")
    ]
    if not logos:
        return None
    english = [logo for logo in logos if logo.get("iso_639_1") == "en"]
    path = max(english or logos, key=lambda logo: logo.get("width") or 0).get("file_path")
    return path if isinstance(path, str) else None


@dataclass(slots=True)
class Enrichment:
    tmdb_id: int
    title: str
    release_year: str | None
    overview: str | None
    tagline: str | None
    rating: float | None
    runtime: int | None
    director: str | None
    genres: list[str] = field(default_factory=list)
    cast: list[dict[str, str]] = field(default_factory=list)
    backdrop_url: str | None = None
    poster_url: str | None = None
    logo_url: str | None = None


def build_enrichment(media_type: str, result: dict[str, Any], detail: dict[str, Any]) -> Enrichment:
    date_field = "release_date" if media_type == "movie" else "first_air_date"
    year_raw = str(detail.get(date_field) or result.get(date_field) or "")[:4]
    crew = (detail.get("credits") or {}).get("crew") or []
    directors = [
        c["name"] for c in crew if c.get("job") in ("Director", "Series Director") and c.get("name")
    ]
    cast_raw = ((detail.get("credits") or {}).get("cast") or [])[:_MAX_CAST]
    images = detail.get("images") or {}
    vote = detail.get("vote_average") or result.get("vote_average")
    backdrop = _best_backdrop(images, result.get("backdrop_path"))
    logo = _best_logo(images)
    poster = detail.get("poster_path") or result.get("poster_path")
    name = (
        detail.get("title") or detail.get("name") or result.get("title") or result.get("name") or ""
    )

    return Enrichment(
        tmdb_id=int(detail.get("id") or result["id"]),
        title=str(name),
        release_year=year_raw if year_raw.isdigit() else None,
        overview=(detail.get("overview") or result.get("overview") or None),
        tagline=(detail.get("tagline") or None),
        rating=round(float(vote), 1) if isinstance(vote, int | float) and vote else None,
        runtime=(detail.get("runtime") or (detail.get("episode_run_time") or [None])[0]),
        director=", ".join(directors) or None,
        genres=[g["name"] for g in (detail.get("genres") or []) if g.get("name")],
        cast=[
            {"name": c["name"], "character": c.get("character") or ""}
            for c in cast_raw
            if c.get("name")
        ],
        backdrop_url=f"{BACKDROP}{backdrop}" if backdrop else None,
        poster_url=f"{POSTER}{poster}" if poster else None,
        logo_url=f"{LOGO}{logo}" if logo else None,
    )
