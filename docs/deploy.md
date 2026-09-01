# Operating tvtimes

This is the reference for what the app expects from its environment. For a
step-by-step self-hosting walkthrough see [`homelab.md`](homelab.md).

The all-in-one image (`issinoho1969/tvtimes`) contains the API, the arq worker and
the built web app. The API serves the SPA from the same origin (`/api/*` to the
backend, everything else to the SPA with a client-routing fallback), so there is
no CORS and the refresh cookie is first-party.

## Processes

| | command | notes |
|---|---|---|
| Web/API | `entrypoint web` | runs `alembic upgrade head`, then `uvicorn` with `--proxy-headers`. Stateless; scale horizontally behind a load balancer. |
| Worker | `entrypoint worker` | `arq app.worker.WorkerSettings`. One is enough — refreshes sources/EPG, warms the TMDB cache, sends watchlist reminders (`reminders`, every 5 min) and source-health alerts (`source_alerts`, every 15 min). |
| Postgres 16 | — | the only stateful store |
| Redis 7 | — | arq queue + rate-limit storage |

The container entrypoint generates `TVTIMES_JWT_PRIVATE_KEY_PEM` and
`TVTIMES_ENCRYPTION_KEY` into `/data` on first run and reuses them forever.
Persist `/data` (a volume) or supply your own via the environment — if those
values ever change, existing sessions and every stored credential become
unreadable.

## Environment (prefix `TVTIMES_`)

**Hard requirements in `env=prod`** — the API refuses to start without them
(`Settings.assert_production_ready`), though the container entrypoint satisfies
the two secrets automatically:

- `TVTIMES_ENV=prod`
- `TVTIMES_JWT_PRIVATE_KEY_PEM` — Ed25519 private key, PKCS#8 PEM
- `TVTIMES_ENCRYPTION_KEY` — 32 urlsafe-base64 bytes (Fernet key)
- `TVTIMES_DATABASE_URL` — `postgres://`, `postgresql://` and
  `postgresql+asyncpg://` are all accepted (the first two are rewritten)
- `TVTIMES_REDIS_URL`

**Expected in any real deployment:**

- `TVTIMES_PUBLIC_ORIGIN` — the exact origin the browser uses. Not `https://`
  is only a warning (self-hosters terminate TLS at their own proxy), but
  passkeys and `Secure` cookies need HTTPS or `localhost`.
- `TVTIMES_WEBAUTHN_RP_ID` — the registrable domain of that origin (no scheme,
  no port); `localhost` for a bare-IP setup. Changing it later invalidates
  every passkey.
- `TVTIMES_RATELIMIT_STORAGE_URI=redis://…` — share the Redis so limits hold
  across API replicas (`memory://` is per-process).
- `TVTIMES_EMAIL_PROVIDER=smtp|resend` + creds — `console` only writes the
  verification/reset link to the log (acceptable for a single-user install).

Full list with defaults: [`.env.example`](../.env.example).

## Edge / reverse proxy

- Terminate TLS at the proxy and forward `X-Forwarded-Proto` / `X-Forwarded-For`
  (uvicorn runs with `--proxy-headers --forwarded-allow-ips '*'`; the rate
  limiter and audit log read the client IP).
- Proxy **all** paths to the container — the SPA and API are one origin.
- Recommended headers: HSTS; CSP with `connect-src 'self'`, `script-src 'self'`,
  `img-src 'self' data: https://image.tmdb.org`. Channel logos are proxied
  through this origin (`/api/channels/{id}/logo`), so only TMDB art is
  cross-origin; the iptv-org logo CDN is fetched server-side only.
- The refresh cookie is `HttpOnly; Secure; SameSite=Lax`, path `/api/auth`.

## Export feeds

If a tenant enables **Settings → Export feeds**, three unauthenticated,
token-gated routes open up — `GET /api/exports/playlist.m3u`, `.../epg.xml`, and
`.../stream/{channel_id}` (a 302 to the resolved upstream). Auth is a
per-tenant token as `?token=`, matched against its sha256; there is nothing to
configure server-side. They are rate-limited (30/min) and safe to expose
through the same proxy as the rest of the app.

## Upgrades

`docker compose pull && docker compose up -d`. The `web` container runs
`alembic upgrade head` on start before serving; the worker waits for it.

## Health

- `GET /api/healthz` — liveness (returns the version). Used by the compose
  healthcheck.
- `GET /api/readyz` — readiness (checks the DB).

## Connector (optional)

`connector/` is a separate agent for HDHomeRun tuners on a network the server
can't reach. Users run `issinoho1969/tvtimes-connector` (or `pipx install
tvtimes-connector`) on that network and pair it from **Settings → Connectors**.
Nothing of it runs server-side beyond `/api/connector/*`. Tuners the server
*can* reach need no connector — add a native **HDHomeRun** source instead.
