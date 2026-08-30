<!-- logo placeholder: frontend/src/assets/brand/logo-lockup.svg -->

# tvtimes

A modern, multi-tenant TV schedule (EPG) site. Create a free account, connect TV
sources (M3U / Xtream / Stalker / HDHomeRun via a LAN connector), and browse a
colourful set-top-box-style guide enriched with channel logos, release years and
a cinematic TMDB "hero" panel.

Hosted at **tvtimes.issinoho.com**. Build plan: [`docs/plan.md`](docs/plan.md) ·
Brand: [`docs/brand.md`](docs/brand.md) · Deploy: [`docs/deploy.md`](docs/deploy.md)

## Status

| Phase | Scope | State |
|------:|-------|-------|
| 1 | Monorepo scaffold, CI, dev stack | done |
| 2 | Auth (passkeys-first, TOTP, rotating sessions) | done |
| 3 | Cloud sources (M3U / Xtream / Stalker) | done |
| 4 | EPG ingest (XMLTV) + timezones | done |
| 5 | Guide UI | done |
| 6 | TMDB enrichment + hero overlay | done |
| 7 | LAN connector (HDHomeRun) | done |
| 8 | Polish (theme toggle, a11y, docs) | in review ([#7](https://github.com/issinoho/tvtimes/pull/7)) |

## Layout

```
backend/     FastAPI + SQLAlchemy 2.0 (async) + Alembic + arq worker
frontend/    React 18 + Vite + TypeScript SPA (PWA)
connector/   Downloadable LAN agent for HDHomeRun tuners
docs/        Plan, brand, and deploy docs
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
