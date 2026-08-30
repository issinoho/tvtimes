<!-- logo placeholder: frontend/src/assets/brand/logo-lockup.svg -->

# tvtimes

A modern, multi-tenant TV schedule (EPG) site. Create a free account, connect TV
sources (M3U / Xtream / Stalker / HDHomeRun / local files), and browse a
colourful set-top-box-style guide enriched with channel logos, release years and
a cinematic TMDB "hero" panel.

Hosted at **tvtimes.issinoho.com**.

## Status

Early development. See [`docs/plan.md`](docs/plan.md) for the build plan and
[`docs/brand.md`](docs/brand.md) for the visual identity.

| Phase | Scope | State |
|------:|-------|-------|
| 1 | Monorepo scaffold, CI, dev stack | done |
| 2 | Auth (passkeys-first, TOTP, rotating sessions) | done |
| 3 | Cloud sources (M3U / Xtream / Stalker) | in review ([#2](https://github.com/issinoho/tvtimes/pull/2)) |
| 4 | EPG ingest (XMLTV) + timezones | — |
| 5 | Guide UI | — |
| 6 | TMDB enrichment + hero overlay | — |
| 7 | LAN connector (HDHomeRun / local files) | — |
| 8 | Polish | — |

## Layout

```
backend/     FastAPI + SQLAlchemy 2.0 (async) + Alembic + arq worker
frontend/    React 18 + Vite + TypeScript SPA
connector/   Downloadable LAN agent (built in phase 7)
docs/        Plan and brand docs
```

## Local development

Requires Docker (Postgres + Redis) and [uv](https://docs.astral.sh/uv/) + Node 20+.

```sh
cp .env.example .env
docker compose up --build
```

- API + docs: http://localhost:8000/docs
- SPA (Vite dev server): http://localhost:5173

Run the backend without Docker (SQLite fallback, no worker):

```sh
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

## Tests

```sh
cd backend && uv run pytest
cd frontend && npm test
```

## Licence

Source parsing and EPG logic is ported and adapted from the
[`tvdinner`](https://github.com/issinoho/tvdinner) CLI (MIT).
