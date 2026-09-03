"""Generate the published OpenAPI document for the **export API**.

The export feeds are tvtimes' only third-party integration surface: a player
(tvdinner), a tuner (Jellyfin, Plex, Emby, TiviMate, Threadfin) or anything else
holding an export token talks to these routes and nothing else. They're the part
worth documenting publicly, and the part whose shape we shouldn't break quietly.

The rest of the API is the SPA's own, and stays undocumented on purpose --
``create_app`` already turns ``/docs`` and ``/openapi.json`` off in prod because
disclosing the whole surface buys an operator nothing. Nothing here changes that:
the export routes keep ``include_in_schema=False`` on the live app, and this
script flips the flag on its own in-process copy purely to render the document.

Regenerate with ``uv run python scripts/export_openapi.py`` from ``backend/``,
and commit the result. CI re-runs it with ``--check`` and fails if the committed
document has drifted from the routes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.api.routers import exports as exports_routes
from app.main import create_app

# Written relative to the repo root, so the docs site can serve it directly.
OUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"

DESCRIPTION = """\
The **export API** is how another application reads a tvtimes account: its whole
merged line-up, the corrected guide, what's been watchlisted and favourited, and
a way to report back what was actually watched.

It is the only part of tvtimes intended for third-party use. Everything else in
the app is the web client's own interface: undocumented, and free to change in
any release. Treat the routes below as the stable surface and the rest as
internal.

## Authentication

Two schemes, deliberately kept on separate paths so they never mix on one route.

**Export token** (`?token=`) — one per account, minted under *Settings → Export
feeds*. It reaches the whole line-up and can stream through it, so treat it as a
password. Rotating it invalidates every feed URL and every saved `tvtimes://`
bookmark at once. It is passed as a query parameter rather than a header because
a tuner or an `<img>`-style client often cannot send one.

`POST /api/exports/watch-events` is the **only write** this token permits, and it
stays narrow: it appends viewing intervals for channels already on the account
and nothing else.

**Play ticket** (`?ticket=`) — a 24-hour, single-channel credential behind the
web app's *Play* button, on the `/play/` routes. Handing someone a programme this
way doesn't hand them the account.

## Conventions

- Channels are identified by tvtimes' own channel UUID in **both** the playlist
  and the guide, so a programme links to its channel 1:1 even where several
  upstream channels share a `tvg-id`.
- Guide times are written **already corrected** into each channel's display zone
  with the right `+ZZZZ` offset. A downstream guide needs no further shifting.
- Every route is rate limited to 30 requests per minute per client.

## Getting a token

*Settings → Export feeds → Generate feed links*. The URLs are shown once. See
[Export Feeds](https://github.com/issinoho/tvtimes/wiki/Export-Feeds) and
[Pairing with tvdinner](https://github.com/issinoho/tvtimes/wiki/Pairing-With-tvdinner).
"""

# OpenAPI's info.version is the *API's* version, not the server build's -- and
# the build's would be "dev" here anyway (app.__version__ reads TVTIMES_VERSION,
# which only a release image sets), so committing it would publish a meaningless
# string and make the CI drift check depend on the environment. This tracks the
# export contract instead: bump it when these routes or their payloads change in
# a way a consumer would notice.
EXPORT_API_VERSION = "1.0"

# FastAPI can't infer these: both credentials are plain query parameters rather
# than Security dependencies, and making them Security() would change runtime
# error handling for a documentation gain. Declared here instead, and applied per
# route below -- the CI drift check keeps the route list honest, though it can't
# check this mapping, so keep it in step by hand when adding a route.
SECURITY_SCHEMES: dict[str, Any] = {
    "exportToken": {
        "type": "apiKey",
        "in": "query",
        "name": "token",
        "description": "Per-account export token from Settings → Export feeds.",
    },
    "playTicket": {
        "type": "apiKey",
        "in": "query",
        "name": "ticket",
        "description": "24-hour, single-channel ticket minted by the web app's Play button.",
    },
}


def build() -> dict[str, Any]:
    # The live app keeps these out of its schema; flip the flag on the router's
    # own route objects before the app is built, so the generated document uses
    # the real mounted paths (/api/exports/...) rather than a hand-stitched
    # prefix that could drift from create_app.
    for route in exports_routes.router.routes:
        route.include_in_schema = True  # type: ignore[attr-defined]

    app = create_app()
    full = app.openapi()
    paths = {p: ops for p, ops in full["paths"].items() if p.startswith("/api/exports")}
    if not paths:  # pragma: no cover - a refactor that moved the prefix
        raise SystemExit("No /api/exports paths found -- has the prefix changed?")

    for path, operations in paths.items():
        scheme = "playTicket" if "/play/" in path else "exportToken"
        for operation in operations.values():
            operation["security"] = [{scheme: []}]
            # Every export route is one tag; the app's own grouping isn't
            # meaningful in a document that contains only these.
            operation["tags"] = ["Export feeds"]

    spec: dict[str, Any] = {
        "openapi": full["openapi"],
        "info": {
            "title": "tvtimes Export API",
            "version": EXPORT_API_VERSION,
            "description": DESCRIPTION,
            "license": {
                "name": "MIT",
                "url": "https://github.com/issinoho/tvtimes/blob/main/LICENSE",
            },
        },
        # There is no canonical server: tvtimes is self-hosted, so the host is
        # whatever the reader deployed. A server variable says that, rather
        # than a placeholder hostname pretending to be real.
        "servers": [
            {
                "url": "https://{host}",
                "description": "Your own tvtimes deployment",
                "variables": {
                    "host": {
                        "default": "tv.example.com",
                        "description": "The host you serve tvtimes on, including any base path.",
                    }
                },
            }
        ],
        "paths": paths,
        "components": {
            **_used_components(full, paths),
            "securitySchemes": SECURITY_SCHEMES,
        },
    }
    return spec


def _used_components(full: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    """Only the schemas these paths actually reference.

    The app's full document carries every model in the API; copying it wholesale
    into a nine-route document would publish the shape of the internal surface
    by the back door, which is the thing we're deliberately not doing."""
    schemas = full.get("components", {}).get("schemas", {})
    wanted: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in wanted:
                    wanted.add(name)
                    walk(schemas.get(name, {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(paths)
    if not wanted:
        return {}
    return {"schemas": {name: schemas[name] for name in sorted(wanted) if name in schemas}}


def main() -> int:
    spec = build()
    rendered = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists():
            print(
                f"{OUT} is missing -- regenerate it (see this module's docstring).",
                file=sys.stderr,
            )
            return 1
        if OUT.read_text() != rendered:
            print(
                f"{OUT} is out of date with the code -- regenerate it and commit.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT.name} is up to date.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered)
    print(f"Wrote {OUT} ({len(spec['paths'])} paths).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
