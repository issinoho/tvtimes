# Deploying tvtimes

Production target: **`tvtimes.issinoho.com`** — the SPA and API served from one
origin (`/api/*` to the backend, the built SPA at the root).

## Components

| | runs as | notes |
|---|---|---|
| API | `uvicorn app.main:app` | stateless; scale horizontally |
| Worker | `arq app.worker.WorkerSettings` | one is enough; refreshes sources/EPG, warms TMDB |
| Postgres 16 | managed | the only stateful store |
| Redis 7 | managed | arq queue + rate-limit storage |
| Object storage (optional) | S3-compatible | raw XMLTV blobs; falls back to a local dir |
| SPA | static files | `cd frontend && npm ci && npm run build` → serve `dist/` |

## Required environment (prefix `TVTIMES_`)

The API **refuses to start** in `env=prod` unless these are real
(`Settings.assert_production_ready`):

- `TVTIMES_ENV=prod`
- `TVTIMES_PUBLIC_ORIGIN=https://tvtimes.issinoho.com` — must be `https://`
- `TVTIMES_JWT_PRIVATE_KEY_PEM` — an Ed25519 private key (PKCS#8 PEM). Generate:
  `python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as K; from cryptography.hazmat.primitives import serialization as s; print(K.generate().private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode())"`
- `TVTIMES_ENCRYPTION_KEY` — 32 urlsafe-base64 bytes (Fernet key); encrypts
  source credentials, TOTP seeds and the TMDB token at rest. Generate:
  `python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`
- `TVTIMES_DATABASE_URL=postgresql+asyncpg://…`
- `TVTIMES_REDIS_URL=redis://…`
- `TVTIMES_RATELIMIT_STORAGE_URI=redis://…` (share the Redis; `memory://` only
  works for a single API process)
- `TVTIMES_WEBAUTHN_RP_ID=tvtimes.issinoho.com` — must equal the origin host
- `TVTIMES_EMAIL_PROVIDER=smtp|resend` plus the matching creds
  (`console` logs the verification link and must not be used in prod)

Full list with defaults: [`.env.example`](../.env.example).

## Rollout

1. `cd backend && uv sync` on the release image.
2. `alembic upgrade head` (run once per deploy, before starting the new API).
3. Start/replace the API and the worker.
4. Build and publish the SPA; point the edge at `dist/` for everything except
   `/api` and `/openapi.json`, which proxy to the API.

## Edge / TLS

- Terminate TLS at the proxy; set `X-Forwarded-For` (the rate limiter and audit
  log read it).
- `HSTS`, and a CSP that allows `connect-src 'self'`, `img-src` also
  `https://image.tmdb.org` and `https://iptv-org.github.io`, `script-src 'self'`.
- The refresh cookie is `HttpOnly; Secure; SameSite=Lax`, path `/api/auth` — no
  extra config, but the SPA and API must share the origin.

## Connector

The LAN connector (`connector/`) is distributed separately — users install it on
their own network (`pipx install tvtimes-connector` or the Docker image) and
pair it from **Settings → Connectors**. Nothing about it runs server-side beyond
the `/api/connector/*` endpoints.

## Health

- `GET /api/healthz` — liveness (version).
- `GET /api/readyz` — readiness (checks the DB).
