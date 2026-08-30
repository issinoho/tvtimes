# CLAUDE.md

Guidance for working in this repo. Keep it current when an invariant changes.

## What this is

A **self-hosted** multi-tenant TV-guide app, distributed as one Docker Compose
stack (published image `issinoho1969/tvtimes`, mirrored to
`ghcr.io/issinoho/tvtimes`). Not a hosted SaaS. Full picture: `README.md`,
`docs/homelab.md`, `docs/deploy.md`.

## Layout

```
backend/    FastAPI · SQLAlchemy 2.0 async · Alembic · arq worker
frontend/   React 18 · Vite · TypeScript · TanStack Query · react-virtual · PWA
connector/  standalone agent for HDHomeRun tuners the server can't reach
docker/     entrypoint.sh — bootstraps secrets, runs migrations, dispatches api|worker
Dockerfile  multi-stage: node builds the SPA -> python image (API + worker + SPA)
```

## Commands

```sh
# backend (run from backend/)
uv sync --extra dev
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -q
uv run alembic revision --autogenerate -m "…"   # then hand-check the migration

# frontend (run from frontend/)
npm ci
npm run lint && npm run typecheck && npm test && npm run build
npm run gen:api      # regenerate src/lib/api/schema.d.ts (needs the API running, or pass a file)

# dev stack
docker compose -f docker-compose.dev.yml up --build
```

CI pins **newer** ruff/mypy than an old local pin may resolve — if `ruff format
--check` passes locally but fails CI, run `uvx ruff@<ci-version> format .`
(the version prints in the failed job log).

## Conventions

- **Python**: 3.12, `from __future__ import annotations`, full type hints, `uv`.
  ruff select = `E,F,I,UP,B,C4,SIM,PTH,RUF`; `mypy` strict (see `pyproject.toml`
  `[tool.mypy]`, `alembic/` excluded). Structured logging via `app.logging`
  (`get_logger`), never bare `print` except the pre-logging startup check.
- **The name is always lowercase `tvtimes`.**
- **Config**: `app/config.py`, env prefix `TVTIMES_`. `get_settings()` is
  `lru_cache`d; tests call `.cache_clear()`.
- **Datetimes**: store UTC. Models use `app.db.TZDateTime` (SQLite returns naive
  — this coerces to aware UTC). Never persist a naive datetime.
- **Outbound HTTP for user-supplied URLs goes through `app/ingest/ssrf.py`**
  (rejects private/loopback/link-local/CGNAT, re-checks redirects, size-caps).
  The one deliberate exception is `app/ingest/hdhomerun.py`, which *requires* a
  private LAN address — don't route it through the generic guard.
- **Secrets** (`config_encrypted`, TOTP seed, TMDB token, connector token) are
  Fernet-encrypted via `app/auth/crypto.py`. Errors/logs are redacted through
  `app/ingest/redact.py`.
- **Frontend**: path alias `@/` → `src/`. API client is `openapi-fetch` over the
  generated `schema.d.ts`; `baseUrl` is the page origin (paths already carry
  `/api`). Component `<Routes>`, not the data router. Guide times **must** be
  formatted in the channel's zone via `features/guide/time.ts` helpers — never
  bare `toLocaleTimeString([])` (see invariants).

## Non-obvious invariants

- **Same-origin.** The API serves the built SPA at `/` (`app.main._mount_spa`,
  gated on `TVTIMES_STATIC_DIR`, mounted *after* the `/api` router). No CORS in
  prod; the refresh cookie is first-party.
- **Cookies.** Refresh token: HttpOnly, `path=/api/auth`. CSRF token:
  non-HttpOnly, **`path=/`** — the SPA reads it from any route to do the silent
  refresh on load. Don't narrow the CSRF path or reloads bounce to login.
- **Guide timezone.** The grid ruler is drawn in `channel.timezone` (per-source
  override → tenant default). Cards, the agenda, the sheet and the day label
  must render in that same zone. Tenant default is set from the browser's IANA
  zone at signup (`RegisterIn.timezone`, validated, UTC fallback).
- **Channel refresh.** `Programme.channel_id` is `ON DELETE CASCADE`.
  `services/sources.refresh_source` reconciles channels **in place** by
  `dedupe_key` (`tvg-id | name | sha1(stream_ref)[:12]`) so unchanged channels
  keep their id and their programmes. It returns `bool` (channel set changed);
  the worker passes `reset_cache=changed` to `epg.ensure_epg_source_for` so a
  changed set forces a full EPG re-parse instead of short-circuiting on a 304.
  The manual `POST /sources/{id}/refresh` also forces it (`force_epg=True`).
- **EPG fan-out.** `epg._channel_index` maps each XMLTV key to a **list** of
  channel ids; `_resolve_channels` returns all of them and a programme row is
  written per channel — so an East/West pair sharing a tvg-id both get data.
- **Email is fail-open.** `auth/email.send_email` catches provider errors, logs
  `email.delivery_failed` + `email.undelivered_body` (so the link is
  recoverable), and returns — a broken mailer must not 500 registration.
- **`SourceKind` enum** is `native_enum=False` (VARCHAR) — adding a value needs
  no migration.

## Workflow

Feature branch → PR → **squash-merge with `--delete-branch`**. CI (`ci.yml`):
backend / connector / frontend / image jobs must pass. Releases are cut by
pushing a tag: `v*` (app image) or `connector-v*` (connector image + wheel);
needs repo secrets `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`. `git remote` is
SSH.
