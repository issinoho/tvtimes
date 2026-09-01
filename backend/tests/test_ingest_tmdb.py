from __future__ import annotations

import respx
from app.ingest.tmdb import (
    _best_backdrop,
    _best_logo,
    build_enrichment,
    guess_title_year,
    guess_trailing_year,
    search,
    strip_embedded_year,
    title_search_candidates,
)
from httpx import AsyncClient, Response


def test_guess_title_year() -> None:
    assert guess_title_year("His Girl Friday (1940)") == ("His Girl Friday", "1940")
    # year first -> everything after it is returned; title_search_candidates trims it
    assert guess_title_year("1940 - His Girl Friday - Cary Grant") == (
        "His Girl Friday - Cary Grant",
        "1940",
    )
    assert guess_title_year("No year here") == ("No year here", None)


def test_guess_trailing_year() -> None:
    assert guess_trailing_year("The Longest Yard (1974)") == ("The Longest Yard", "1974")
    assert guess_trailing_year("The Longest Yard [1974]") == ("The Longest Yard", "1974")
    # no parens -> the number is part of the actual title, not a year to extract
    assert guess_trailing_year("1917") == ("1917", None)
    assert guess_trailing_year("Blade Runner 2049") == ("Blade Runner 2049", None)
    assert guess_trailing_year("2001: A Space Odyssey") == ("2001: A Space Odyssey", None)
    # a year elsewhere than the trailing position doesn't match either
    assert guess_trailing_year("1940 - His Girl Friday") == ("1940 - His Girl Friday", None)
    assert guess_trailing_year("No year here") == ("No year here", None)


def test_title_search_candidates() -> None:
    assert title_search_candidates("His Girl Friday - Cary Grant - ...") == [
        "His Girl Friday",
        "His Girl Friday - Cary Grant - ...",
    ]
    assert title_search_candidates("Mission: Impossible") == ["Mission: Impossible"]


def test_strip_embedded_year() -> None:
    assert strip_embedded_year("Confessions (1977)", "1977") == "Confessions"
    assert strip_embedded_year("Something (Else)", "1977") == "Something (Else)"


def test_best_backdrop_prefers_textless_then_width() -> None:
    images = {
        "backdrops": [
            {"file_path": "/en.jpg", "iso_639_1": "en", "width": 3000},
            {"file_path": "/textless.jpg", "iso_639_1": None, "width": 1280},
            {"file_path": "/textless-big.jpg", "iso_639_1": None, "width": 1920},
        ]
    }
    assert _best_backdrop(images, "/fallback.jpg") == "/textless-big.jpg"
    assert _best_backdrop({"backdrops": []}, "/fallback.jpg") == "/fallback.jpg"


def test_best_logo_prefers_english_non_svg() -> None:
    images = {
        "logos": [
            {"file_path": "/x.svg", "iso_639_1": "en", "width": 9000},
            {"file_path": "/fr.png", "iso_639_1": "fr", "width": 800},
            {"file_path": "/en.png", "iso_639_1": "en", "width": 500},
        ]
    }
    assert _best_logo(images) == "/en.png"
    assert _best_logo({"logos": [{"file_path": "/only.svg"}]}) is None


def test_build_enrichment_movie() -> None:
    result = {"id": 42, "vote_average": 7.84, "backdrop_path": "/b.jpg"}
    detail = {
        "id": 42,
        "title": "The Thing",
        "release_date": "1982-06-25",
        "overview": "A shape-shifter.",
        "tagline": "Man is the warmest place to hide.",
        "runtime": 109,
        "genres": [{"name": "Horror"}, {"name": "Sci-Fi"}],
        "credits": {
            "crew": [{"job": "Director", "name": "John Carpenter"}],
            "cast": [{"name": "Kurt Russell", "character": "MacReady"}, {"name": "Extra"}],
        },
        "images": {
            "backdrops": [{"file_path": "/big.jpg", "iso_639_1": None, "width": 3840}],
            "logos": [{"file_path": "/logo.png", "iso_639_1": "en", "width": 1000}],
        },
    }
    e = build_enrichment("movie", result, detail)
    assert e.tmdb_id == 42
    assert e.title == "The Thing"
    assert e.release_year == "1982"
    assert e.rating == 7.8
    assert e.runtime == 109
    assert e.director == "John Carpenter"
    assert e.genres == ["Horror", "Sci-Fi"]
    assert e.cast == [
        {"name": "Kurt Russell", "character": "MacReady"},
        {"name": "Extra", "character": ""},
    ]
    assert e.backdrop_url == "https://image.tmdb.org/t/p/w1280/big.jpg"
    assert e.logo_url == "https://image.tmdb.org/t/p/w500/logo.png"


@respx.mock
async def test_search_prefers_the_year_embedded_in_the_title() -> None:
    """No <date> from the source, but the title itself says "(1974)" -- the
    1974 original must win over the far more popular 2005 remake, both
    titled identically by TMDB."""
    remake = {"id": 2005, "title": "The Longest Yard", "release_date": "2005-05-27"}
    original = {"id": 1974, "title": "The Longest Yard", "release_date": "1974-08-21"}
    route = respx.get(f"{'https://api.themoviedb.org/3'}/search/movie").mock(
        return_value=Response(200, json={"results": [remake, original]})
    )
    async with AsyncClient() as http:
        result = await search(http, "movie", "The Longest Yard (1974)", None, "tok")

    assert result is not None and result["id"] == 1974
    sent_query = dict(route.calls.last.request.url.params)["query"]
    assert sent_query == "The Longest Yard"  # the embedded year is stripped from the query


@respx.mock
async def test_search_without_any_year_signal_falls_back_to_first_result() -> None:
    """No <date> and no embedded year -> unchanged behaviour: TMDB's own
    relevance/popularity order wins (there's nothing left to disambiguate on)."""
    remake = {"id": 2005, "title": "The Longest Yard", "release_date": "2005-05-27"}
    original = {"id": 1974, "title": "The Longest Yard", "release_date": "1974-08-21"}
    respx.get(f"{'https://api.themoviedb.org/3'}/search/movie").mock(
        return_value=Response(200, json={"results": [remake, original]})
    )
    async with AsyncClient() as http:
        result = await search(http, "movie", "The Longest Yard", None, "tok")

    assert result is not None and result["id"] == 2005


@respx.mock
async def test_search_tolerates_an_off_by_one_feed_year() -> None:
    """The feed says 1973, TMDB's original is 1974 -- close enough to beat the
    2005 remake, which no exact-year match would have caught."""
    remake = {"id": 2005, "title": "The Longest Yard", "release_date": "2005-05-27"}
    original = {"id": 1974, "title": "The Longest Yard", "release_date": "1974-08-21"}
    respx.get(f"{'https://api.themoviedb.org/3'}/search/movie").mock(
        return_value=Response(200, json={"results": [remake, original]})
    )
    async with AsyncClient() as http:
        result = await search(http, "movie", "The Longest Yard", "1973", "tok")

    assert result is not None and result["id"] == 1974


@respx.mock
async def test_search_ignores_a_wildly_wrong_feed_year() -> None:
    """No candidate within the tolerance window -> fall back to TMDB's ranking,
    don't let a bad feed year pull the match somewhere random."""
    remake = {"id": 2005, "title": "The Longest Yard", "release_date": "2005-05-27"}
    original = {"id": 1974, "title": "The Longest Yard", "release_date": "1974-08-21"}
    respx.get(f"{'https://api.themoviedb.org/3'}/search/movie").mock(
        return_value=Response(200, json={"results": [remake, original]})
    )
    async with AsyncClient() as http:
        result = await search(http, "movie", "The Longest Yard", "1990", "tok")

    assert result is not None and result["id"] == 2005


def test_cache_key_falls_back_to_title_embedded_year() -> None:
    from app.services.tmdb import cache_key

    assert cache_key("The Longest Yard (1974)", None) == ("the longest yard", "1974")
    # an explicit year always wins over anything embedded in the title
    assert cache_key("The Longest Yard (1974)", "2005") == (
        "the longest yard (1974)",
        "2005",
    )
    assert cache_key("The Longest Yard", None) == ("the longest yard", "")
