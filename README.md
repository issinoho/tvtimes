<p align="center">
  <img src="docs/logo.svg" alt="tvtimes" width="460">
</p>

<p align="center">
  A modern, self-hosted TV schedule (EPG) for your home lab — colourful
  set-top-box-style guide, passkeys-first accounts, one Docker Compose stack.
</p>

<p align="center">
  <a href="https://issinoho.github.io/tvtimes/"><img alt="Website" src="https://img.shields.io/badge/website-issinoho.github.io%2Ftvtimes-DB2777"></a>
  <a href="https://hub.docker.com/r/issinoho1969/tvtimes"><img alt="Docker Hub" src="https://img.shields.io/badge/docker-issinoho1969%2Ftvtimes-2496ED?logo=docker&logoColor=white"></a>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-6D28D9">
</p>

---

## What it is

Create an account, connect your TV sources, and browse a fast, virtualised
guide grid enriched with channel logos, release years, genres and a cinematic
TMDB "hero" panel. Everything runs on your own hardware.

| | |
|---|---|
| **Sources** | M3U / M3U8 playlists · Xtream Codes · Stalker portals · **HDHomeRun** (native discovery, or the connector agent for tuners on another network). Drag to reorder them — the guide lists channels source-by-source in that order. |
| **Guide** | virtualised grid + live "now" line on desktop, single-channel agenda on phones; genre colours, date nav, group filter, channel search, full keyboard nav; programme labels stay pinned as you scroll through a long film; installable PWA with an offline shell and an in-app "new version" prompt |
| **Time** | one account timezone (captured from your browser at signup) with a per-source override and a per-channel offset you nudge from a programme's info panel — line a US-West feed up with an East-coast EPG without touching its sibling |
| **Enrichment** | your own TMDB API key powers backdrops, logos, cast, ratings and synopses for film programmes. Channel logos come from the playlist, else the iptv-org database, else the SiliconDust guide for HDHomeRun — shown on a neutral plate so dark and light marks both read |
| **Export** | hand your whole line-up to another player — one merged, de-duplicated **M3U playlist** + **XMLTV guide** (times already timezone-corrected per channel) behind a rotatable token. Drop the two URLs into Jellyfin, Plex, Emby, TiviMate or Threadfin |
| **Auth** | WebAuthn passkeys first (with a clear message when the RP-ID/origin is misconfigured), Argon2id password + HIBP check as a fallback, TOTP 2FA, 60-day rotating refresh sessions with replay detection, a device/session list (one row per login), audit log |

## Run it

You need Docker with the Compose plugin. Nothing to build — it pulls a
published multi-arch image (`linux/amd64` + `linux/arm64`).

Make a directory, drop in the two files below, then `docker compose up -d`.

**`.env`** — the only line you must set is `TVTIMES_PUBLIC_ORIGIN`:

```sh
TVTIMES_PUBLIC_ORIGIN=http://localhost:8888   # the exact URL you'll open
TVTIMES_WEBAUTHN_RP_ID=localhost              # the origin's domain; keep as localhost for a bare-IP setup
POSTGRES_PASSWORD=change-me
# TVTIMES_EMAIL_PROVIDER=smtp                 # optional; default logs the verification link
```

<details>
<summary><b><code>docker-compose.yml</code></b> — copy verbatim</summary>

```yaml
name: tvtimes

x-app: &app
  image: ${TVTIMES_IMAGE:-issinoho1969/tvtimes:latest}
  restart: unless-stopped
  env_file:
    - .env          # everything in .env reaches the container; the values below still win
  environment:
    TVTIMES_ENV: prod
    TVTIMES_DATABASE_URL: postgresql+asyncpg://tvtimes:${POSTGRES_PASSWORD:-tvtimes}@db:5432/tvtimes
    TVTIMES_REDIS_URL: redis://redis:6379/0
    TVTIMES_RATELIMIT_STORAGE_URI: redis://redis:6379/1
    TVTIMES_PUBLIC_ORIGIN: ${TVTIMES_PUBLIC_ORIGIN:?set TVTIMES_PUBLIC_ORIGIN in .env}
    TVTIMES_WEBAUTHN_RP_ID: ${TVTIMES_WEBAUTHN_RP_ID:-localhost}
    TVTIMES_WEBAUTHN_RP_NAME: ${TVTIMES_WEBAUTHN_RP_NAME:-tvtimes}
    TVTIMES_EMAIL_PROVIDER: ${TVTIMES_EMAIL_PROVIDER:-console}
    TVTIMES_EMAIL_FROM: ${TVTIMES_EMAIL_FROM:-tvtimes <no-reply@localhost>}
    TVTIMES_SMTP_HOST: ${TVTIMES_SMTP_HOST:-}
    TVTIMES_SMTP_PORT: ${TVTIMES_SMTP_PORT:-587}
    TVTIMES_SMTP_USERNAME: ${TVTIMES_SMTP_USERNAME:-}
    TVTIMES_SMTP_PASSWORD: ${TVTIMES_SMTP_PASSWORD:-}
    TVTIMES_RESEND_API_KEY: ${TVTIMES_RESEND_API_KEY:-}
  volumes:
    - secrets:/data
  depends_on:
    db: { condition: service_healthy }
    redis: { condition: service_healthy }

services:
  tvtimes:
    <<: *app
    command: ["web"]
    ports:
      - "${TVTIMES_HTTP_PORT:-8888}:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/healthz', timeout=3).status==200 else 1)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s

  worker:
    <<: *app
    command: ["worker"]
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
      tvtimes: { condition: service_started }

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: tvtimes
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-tvtimes}
      POSTGRES_DB: tvtimes
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tvtimes"]
      interval: 10s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
  redisdata:
  secrets:
```

</details>

Prefer to fetch them?

```sh
curl -O https://raw.githubusercontent.com/issinoho/tvtimes/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/issinoho/tvtimes/main/.env.example
```

Then:

```sh
docker compose up -d
```

Open the origin you configured (default `http://localhost:8888`) and create the
first account. With the default `TVTIMES_EMAIL_PROVIDER=console`, the
verification link is printed to the log:

```sh
docker compose logs tvtimes | grep -E "email.console|email.undelivered_body"
```

One container serves the API **and** the web app on port 8888; a second runs the
background worker. Postgres, Redis and the auto-generated secrets live in named
volumes, so accounts and sessions survive `docker compose pull && docker compose up -d`.

### Essential configuration

| Variable | Notes |
|---|---|
| `TVTIMES_PUBLIC_ORIGIN` | The exact URL the browser uses — scheme, host, port, no trailing slash. Passkeys are bound to it. `http://192.168.x.x:8888` is fine on a trusted LAN; use `https://…` behind a reverse proxy. |
| `TVTIMES_WEBAUTHN_RP_ID` | The registrable domain of that origin (no scheme/port); `localhost` for a bare-IP setup. **Changing it later invalidates every passkey.** |
| `TVTIMES_HTTP_PORT` | Host port to expose (default `8888`). |
| `POSTGRES_PASSWORD` | Used by the db container and the app connection string. |
| `TVTIMES_EMAIL_PROVIDER` | `console` (log only) · `smtp` (+ `TVTIMES_SMTP_*`) · `resend` (+ `TVTIMES_RESEND_API_KEY`). |

Full list with comments: [`.env.example`](.env.example). Secrets
(`TVTIMES_JWT_PRIVATE_KEY_PEM`, `TVTIMES_ENCRYPTION_KEY`) are generated into the
`secrets` volume on first run — **back that volume up**; if it's lost, stored
credentials and sessions can't be decrypted.

### Behind a reverse proxy (HTTPS)

Passkeys and `Secure` cookies need HTTPS (or `localhost`). Terminate TLS at your
proxy and forward everything to the container. In `.env`:

```sh
TVTIMES_PUBLIC_ORIGIN=https://tv.example.com
TVTIMES_WEBAUTHN_RP_ID=tv.example.com
```

Caddy:

```
tv.example.com {
    reverse_proxy 127.0.0.1:8888
}
```

The app already trusts `X-Forwarded-Proto` / `X-Forwarded-For`.

### HDHomeRun

Add a source → **HDHomeRun**:

- **Server on the tuner's network, not in Docker's bridge:** leave the address
  blank to auto-discover.
- **tvtimes in Docker (usual case):** the bridge network can't receive
  discovery broadcasts — enter the tuner's LAN address, e.g. `http://192.168.1.50`.
- **Tuner on a different network from the server:** run
  [`issinoho1969/tvtimes-connector`](connector/README.md) there and pair it from
  **Settings → Connectors**.

SiliconDust guide data (`api.hdhomerun.com`) is adopted automatically when the
tuner reports a `DeviceAuth`.

### Backups & upgrades

```sh
# upgrade
docker compose pull && docker compose up -d --force-recreate   # migrations run on start

# database backup
docker compose exec db pg_dump -U tvtimes tvtimes | gzip > tvtimes-$(date +%F).sql.gz
```

`--force-recreate` makes Compose swap containers onto the freshly pulled image
(plain `up -d` sometimes reports "Running" and skips it). Open tabs pick up the
new web app via the "new version available — Reload" prompt.

Volumes: `tvtimes_pgdata` (accounts, sources, guide), `tvtimes_secrets` (signing
+ encryption keys — **back up**), `tvtimes_redisdata` (queue/cache, safe to lose).

More detail: [`docs/homelab.md`](docs/homelab.md) · ops reference:
[`docs/deploy.md`](docs/deploy.md).

## Images

| Image | Purpose |
|---|---|
| `issinoho1969/tvtimes` · `ghcr.io/issinoho/tvtimes` | all-in-one: API + worker + web app |
| `issinoho1969/tvtimes-connector` · `ghcr.io/issinoho/tvtimes-connector` | optional LAN agent for off-network HDHomeRun tuners |

## Architecture

```
backend/     FastAPI · SQLAlchemy 2.0 (async) · Alembic · arq worker · Postgres 16 · Redis 7
frontend/    React 18 · Vite · TypeScript · TanStack Query · @tanstack/react-virtual · PWA
connector/   Standalone Python agent (outbound HTTPS only) for off-network tuners
docker/      Container entrypoint (secret bootstrap · migrations · api|worker dispatch)
docs/        homelab · deploy · brand
```

The API serves the built SPA from the **same origin** (`/api/*` to the backend,
everything else to the app with a client-routing fallback), so there is no CORS
and the refresh cookie is first-party.

## Local development

```sh
docker compose -f docker-compose.dev.yml up --build
```

- API + interactive docs: <http://localhost:8000/docs>
- SPA dev server (HMR): <http://localhost:5173>

Backend only (SQLite, no worker):

```sh
cd backend && uv sync && uv run uvicorn app.main:app --reload
```

Working conventions and the non-obvious invariants are in
[`CLAUDE.md`](CLAUDE.md).

### Tests & checks

```sh
cd backend  && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -q
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## Releases

| Tag | Publishes |
|---|---|
| `v*` | `issinoho1969/tvtimes` + GHCR mirror, multi-arch |
| `connector-v*` | connector image + the wheel/sdist on the GitHub Release |

## Contributing

Bug reports, ideas and PRs welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md)
and the [`Code of Conduct`](CODE_OF_CONDUCT.md). Security issues go through
[`SECURITY.md`](SECURITY.md), not a public issue.

## Licence

[MIT](LICENSE). Source parsing and EPG logic is adapted from the
[`tvdinner`](https://github.com/issinoho/tvdinner) CLI (MIT). Brand mark built
from openly-licensed base glyphs — see [`docs/brand.md`](docs/brand.md).
