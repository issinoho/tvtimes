from __future__ import annotations

from app.ingest.tmdb import (
    _best_backdrop,
    _best_logo,
    build_enrichment,
    guess_title_year,
    strip_embedded_year,
    title_search_candidates,
)


def test_guess_title_year() -> None:
    assert guess_title_year("His Girl Friday (1940)") == ("His Girl Friday", "1940")
    # year first -> everything after it is returned; title_search_candidates trims it
    assert guess_title_year("1940 - His Girl Friday - Cary Grant") == (
        "His Girl Friday - Cary Grant",
        "1940",
    )
    assert guess_title_year("No year here") == ("No year here", None)


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
