<!-- logo placeholder: frontend/src/assets/brand/logo-lockup.svg -->

# tvtimes

A modern, self-hostable TV schedule (EPG) site. Create an account, connect TV
sources (M3U / Xtream / Stalker / HDHomeRun), and browse a colourful
set-top-box-style guide enriched with channel logos, release years and a
cinematic TMDB "hero" panel. Passkeys-first auth, long-lived sessions, works on
phones and tablets, installable as a PWA.

Build plan: [`docs/plan.md`](docs/plan.md) · Brand: [`docs/brand.md`](docs/brand.md)
· Self-hosting: [`docs/homelab.md`](docs/homelab.md) · Ops notes: [`docs/deploy.md`](docs/deploy.md)

## Run it (Docker Compose)

You need Docker with the Compose plugin. Nothing to build — it pulls a
published image.

```sh
curl -O https://raw.githubusercontent.com/issinoho/tvtimes/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/issinoho/tvtimes/main/.env.example
# edit .env: set TVTIMES_PUBLIC_ORIGIN (and TVTIMES_WEBAUTHN_RP_ID for a domain)
docker compose up -d
```

Open the origin you set and create the first account. One container serves both
the API and the web app on port 8000; a second runs the background worker.
Postgres, Redis, and the auto-generated secrets live in named volumes, so
accounts and sessions survive `docker compose pull && docker compose up -d`.

Full walkthrough — reverse proxy + TLS, HDHomeRun, email, backups, upgrades — in
[`docs/homelab.md`](docs/homelab.md).

### Images

| Image | Purpose |
|-------|---------|
| `issinoho/tvtimes` (`ghcr.io/issinoho/tvtimes`) | all-in-one: API + worker + web app |
| `issinoho/tvtimes-connector` (`ghcr.io/issinoho/tvtimes-connector`) | optional LAN agent for HDHomeRun tuners on a network the server can't reach |

Native HDHomeRun support is built in — add an **HDHomeRun** source and either
let it auto-discover or enter the tuner's LAN address (needed when tvtimes runs
on Docker's default bridge network, which can't receive discovery broadcasts).
The connector is only for tuners on a different network from the server.

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
| 8 | Polish (theme toggle, a11y, docs) | done |
| — | Homelab packaging + native HDHomeRun | done |

## Layout

```
backend/     FastAPI + SQLAlchemy 2.0 (async) + Alembic + arq worker
frontend/    React 18 + Vite + TypeScript SPA (PWA)
connector/   Optional LAN agent for off-network HDHomeRun tuners
docker/      Container entrypoint
docs/        Plan, brand, self-hosting, and ops docs
```

## Local development

Requires Docker and [uv](https://docs.astral.sh/uv/) + Node 22+.

```sh
docker compose -f docker-compose.dev.yml up --build
```

- API + docs: http://localhost:8000/docs
- SPA (Vite dev server, HMR): http://localhost:5173

Backend only (SQLite fallback, no worker):

```sh
cd backend && uv sync && uv run uvicorn app.main:app --reload
```

## Tests

```sh
cd backend && uv run pytest
cd frontend && npm test
```

## Licence

Source parsing and EPG logic is ported and adapted from the
[`tvdinner`](https://github.com/issinoho/tvdinner) CLI (MIT).
