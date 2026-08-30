# tvtimes — multi-tenant TV schedule site

## Context

`/home/iain/projects/tvtimes` is empty. The goal is a new **hosted, multi-tenant
web app** where anyone can create a free account, configure TV sources (M3U,
Xtream, Stalker, HDHomeRun, local files — the same source types the existing
`tvdinner` CLI supports), and browse a colourful, set-top-box-style EPG enriched
with logos, screenshots, release year and a cinematic TMDB "hero" panel.

The reference project `/home/iain/projects/tvdinner` (Python CLI) already contains
well-factored, pure-Python parsers for every source type, XMLTV/EPG parsing with
timezone + clock-correction handling, and a TMDB enrichment layer. Those modules
are almost entirely free of CLI/mpv coupling and will be **ported into the
backend** rather than rewritten.

### Decisions (from the user)

- **Hosting:** hosted SaaS + a small downloadable **connector** agent for
  LAN-only sources (HDHomeRun, local files). Cloud sources (remote
  M3U/Xtream/Stalker/XMLTV URLs) work without it.
- **Backend:** Python + FastAPI (async), reusing tvdinner's parsing code.
- **Frontend:** React SPA (Vite + TypeScript) talking to the API.
- **Auth:** own auth, passkeys-first (WebAuthn primary; email+password Argon2id
  fallback; TOTP 2FA; long-lived rotating refresh sessions so the user is not
  nagged for credentials).

### Upstream

`https://github.com/issinoho/tvtimes` exists but is **empty** (description: "A
modern convenient schedule EPG pulling from multiple online sources"). Phase 1
initialises the monorepo here: `git init`, add this remote, first commit is the
scaffold, work proceeds on feature branches.

### Assumptions (sensible defaults, change on request)

- Transactional email via a pluggable provider (Resend/SES/SMTP); dev prints the
  link to the console.
- Both a dark ("colour wash") theme and a matching light theme.
- The connector is built last (phase 7); cloud sources are fully usable before it.
- One user = one tenant for v1, but `tenant` is modelled separately so shared
  household accounts are a later addition, not a migration.

---

## Architecture

Monorepo:

```
tvtimes/
  backend/            FastAPI app, SQLAlchemy 2.0 async, Alembic, arq worker
    app/
      main.py  config.py  db.py
      models/          ORM: tenant, user, password_credential, webauthn_credential,
                       totp_secret, auth_session, email_token, source, epg_source,
                       channel, programme, tmdb_enrichment, connector, audit_log
      schemas/         Pydantic v2 DTOs
      auth/            webauthn.py, passwords.py, tokens.py, totp.py, email.py, deps.py
      ingest/          PORTED FROM tvdinner (see below): m3u.py, xtream.py, stalker.py,
                       hdhomerun.py, epg_xmltv.py, tmdb.py, channel_logos.py,
                       redact.py, movietitle.py, normalize.py, ssrf.py
      services/        source_service, epg_service, guide_service, tmdb_service, tz_service
      workers/         tasks.py (refresh_source, refresh_epg, enrich_programme)
      api/routers/     auth.py, account.py, sources.py, epg.py, guide.py, tmdb.py,
                       channels.py, connector.py
    alembic/  tests/  pyproject.toml
  frontend/            React 18 + Vite + TS
    src/
      lib/api/         openapi-typescript + openapi-fetch client (generated from /openapi.json)
      features/auth/   sign-up, verify, passkey register/login, 2FA, sessions
      features/sources/ source wizard + status
      features/guide/  the EPG grid (centrepiece)
      features/hero/   cinematic TMDB overlay
      features/settings/ account, timezones, connectors, TMDB key
      styles/          theme.css (design tokens + colour wash)
      assets/brand/    logo-mark.svg, logo-lockup.svg, favicons
  connector/            downloadable LAN agent (Python; PyInstaller binary + Docker image)
  docker-compose.yml    postgres 16, redis 7, backend, worker, frontend dev
  docs/brand.md
  .github/workflows/ci.yml
```

Runtime services: FastAPI (uvicorn), arq worker (Redis-backed), Postgres, Redis,
S3-compatible object storage for raw XMLTV blobs. TLS at the edge; app secrets
via env/secret manager.

### Deployment target

Production host: **`tvtimes.issinoho.com`**. The SPA and API are served from the
same origin (API under `/api`, SPA static assets at the root) so the refresh
cookie is first-party and no CORS is needed in prod; dev uses a Vite proxy to
`localhost:8000`. WebAuthn **RP ID = `tvtimes.issinoho.com`**, RP name
"tvtimes", origin `https://tvtimes.issinoho.com`. Refresh cookie scoped to that
host (no parent-domain sharing). CSP `connect-src 'self'`; `img-src` also allows
`image.tmdb.org` and the iptv-org logo CDN.

---

## Backend detail

### Porting from tvdinner (`/home/iain/projects/tvdinner/src/tvdinner/`)

All of these are pure `requests` + stdlib and lift with light edits:

| New file | Source | Adaptation |
|---|---|---|
| `ingest/m3u.py` | `m3u.py` | `load_playlist`, `parse_m3u`, `Channel`/`Playlist`. Route fetches through `ssrf.py`. |
| `ingest/xtream.py` | `xtream.py` | `load_xtream_playlist`, `xtream_epg_url`. Creds stay encrypted; build stream URLs on demand — never persist creds in `channel.stream_ref`. |
| `ingest/stalker.py` | `stalker.py` | `load_stalker_playlist`. Resolve `create_link` **lazily** at stream-redirect time, not at ingest (URLs are short-lived, portals rate-limit). MAC encrypted. |
| `ingest/hdhomerun.py` | `hdhomerun.py` | `discover.json` / `lineup.json` logic runs **inside the connector**; backend just receives lineups. Jitter the SiliconDust cloud-XMLTV fetch. |
| `ingest/epg_xmltv.py` | `epg.py` | Keep `parse_xmltv` (streaming ElementTree), `parse_xmltv_time`, `EpgDisplay` shift/timezone model, gzip sniff. Replace file cache with: raw XML → object storage, parsed programmes → Postgres rows. **Add** HTTP conditional GET (ETag / If-Modified-Since) which tvdinner lacks. |
| `ingest/normalize.py` | `epg.py` | Extract `normalize_name`, `resolve_channel_id`, `FEED_SUFFIX_RE` for programme↔channel matching. We have real DB ids, so per-channel clock shift is a `channel` column, not tvdinner's display-name-keyed JSON hack. |
| `ingest/channel_logos.py` | `channel_logos.py` | iptv-org index; cache in Redis, refresh daily; return URL strings for the browser `<img>`. |
| `ingest/tmdb.py` | `tmdb.py` | Keep `_search_movie`/`_search_tv`, `_best_backdrop_path`, `_best_logo_path`, `_movie_metadata_from_result`, `_strip_embedded_year`, `is_movie_category`, and the design rules: never send `year` as a hard filter (client-side candidate pick), strip `(YYYY)` suffix, cache genuine negatives but **never** cache request failures, prefer textless backdrops + English non-SVG logos + max width, gate on movie-category so a wrong match is never shown. **Upgrade:** use `append_to_response=credits,images` on `/movie/{id}` & `/tv/{id}` for genres + cast + images in one call; fetch `/configuration` once/day (Redis) instead of hardcoding image bases. |
| `ingest/movietitle.py` | `movietitle.py` | `guess_title_year`, `title_search_candidates` — verbatim, for TMDB candidate generation. |
| `ingest/redact.py` | `redact.py` + `xtream.redact_xtream_url` + `stalker.redact_stalker_url` | Verbatim; wire into structlog processors so no secret is ever logged. |
| `ingest/ssrf.py` | new | Resolve hostname, reject loopback/private/link-local/ULA ranges (incl. `169.254.169.254`), cap body size, bounded timeout, no cross-host redirect. Applied to every user-supplied URL fetch. |

tvdinner's `tests/` fixtures for m3u/xtream/xmltv parsing are reusable — copy the
relevant ones into `backend/tests/fixtures/`.

### Data model highlights

- **tenant**: `default_timezone` (IANA), `tmdb_api_token_encrypted`, `tmdb_token_added_at`.
- **source**: `kind`, `display_name`, `config_encrypted` (JSON: url/creds/host),
  `timezone_override` (nullable IANA), `clock_shift_seconds`, `connector_id`
  (nullable), `enabled`, `refresh_interval_minutes`, `last_status`, `last_error`,
  `last_refreshed_at`.
- **epg_source**: `source_id` (nullable — standalone XMLTV allowed), `url` or
  `"auto"`, `etag`, `last_modified`, `last_fetched_at`, `status`.
- **channel**: `source_id`, `ext_id` (tvg-id), `name`, `tvg_name`, `logo_url`,
  `group_title`, `number`, `sort_order`, `hd`, `stream_ref` (template, no creds),
  `clock_shift_seconds` (per-channel override), `last_seen_at`.
- **programme**: `channel_id`, `start_utc`, `stop_utc`, `title`, `sub_title`,
  `description`, `category text[]`, `episode_num`, `year`, `icon_url`,
  `is_movie`, `tmdb_enrichment_id` (nullable). Indexes: `(channel_id, start_utc)`,
  `(tenant_id, start_utc)`.
- **tmdb_enrichment**: **global** cache (content is public), keyed
  `(media_type, normalized_title, year)`; `tmdb_id`, `title`, `release_year`,
  `overview`, `rating`, `genres text[]`, `director`, `cast jsonb`,
  `backdrop_url`, `poster_url`, `logo_url`, `fetched_at`, `negative bool`.
  30-day TTL.
- **connector**: `pairing_code`, `token_hash`, `last_seen_at`, `version`,
  `status`, `discovered jsonb`.
- Encryption: AES-GCM (via `cryptography`) with a per-record nonce; app key from
  secret manager. Covers TMDB token, source creds, TOTP secret, connector token.
- Every tenant-scoped query filters on `tenant_id` from the auth context
  (helper dependency `current_tenant`); no cross-tenant row is reachable.

### Auth

- Libraries: `webauthn` (py_webauthn), `argon2-cffi`, `pyotp`, `PyJWT` (EdDSA),
  `slowapi` (Redis rate limiting).
- **Sign-up:** email + display name → create `tenant` + `user` → hashed
  short-lived verification token emailed → on verify, prompt to add a passkey.
  Password is optional; if set, enforce length + HIBP k-anonymity range check.
- **Login:** passkey via conditional UI (autofill) primary; or email+password →
  TOTP step if enabled. Enumeration-resistant responses; lockout with
  exponential backoff; audit-logged.
- **Sessions:** access JWT (EdDSA, 15 min, held in SPA memory); refresh token
  opaque 256-bit in `HttpOnly; Secure; SameSite=Lax` cookie, 60-day sliding,
  **rotated every use with reuse detection** (replay ⇒ revoke whole chain).
  Double-submit CSRF token on the refresh/logout endpoints. "Remember me" is
  always on for this product.
- **2FA:** TOTP with QR enrolment + 10 single-use hashed recovery codes.
- Hardening: HSTS, strict CSP (no inline JS), secure cookies, generic errors,
  password reset via hashed token, optional new-login email, tuned Argon2id
  params, structured audit log.

### Workers (arq on Redis)

- `refresh_source(source_id)` — fetch + parse + upsert channels; on source
  create/edit it runs immediately, then on `refresh_interval_minutes`
  (default 6h channels).
- `refresh_epg(epg_source_id)` — conditional GET; parse; upsert programmes in
  the rolling window (−1d … +14d); prune stale; default 12h, jittered.
- `enrich_programme(...)` — after an EPG refresh, for movie-category programmes
  in the next ~7 days, populate `tmdb_enrichment` (global cache first, then
  TMDB). Per-token Redis token-bucket rate limit.

### Timezones

Store everything UTC. At query time resolve display tz =
`source.timezone_override or tenant.default_timezone`; apply
`channel.clock_shift_seconds or source.clock_shift_seconds` as a `timedelta`
added to programme times, then `astimezone()` — tvdinner's exact two-part model
(`EpgDisplay.to_local` / `now_and_next`).

### Key endpoints

`POST /auth/register`, `/auth/verify`, `/auth/webauthn/register/{begin,complete}`,
`/auth/webauthn/login/{begin,complete}`, `/auth/login`, `/auth/totp/*`,
`/auth/refresh`, `/auth/logout`, `/auth/sessions` (list/revoke) ·
`GET/POST/PATCH/DELETE /sources`, `POST /sources/{id}/refresh` ·
`GET/POST/DELETE /epg-sources` ·
`GET /guide?from&to&groups&channels` (grid payload, virtualisation-friendly),
`GET /channels/{id}/schedule`, `GET /guide/programme/{id}/hero` ·
`PUT /account/tmdb-token`, `PATCH /account/timezone` ·
`POST /connector/pair`, `/connector/heartbeat`, `/connector/lineup`,
`/connector/resolve`.

---

## Frontend detail

Stack: React 18, TypeScript, Vite, React Router, TanStack Query, Zustand (light
UI state), `openapi-typescript` + `openapi-fetch` (typed client from
`/openapi.json`), Framer Motion (hero + guide motion), `@simplewebauthn/browser`
(passkeys), `@tanstack/react-virtual` (grid).

Screens:

- **Onboarding:** sign up → verify → add passkey → source wizard (one form per
  kind, live validation) → optional TMDB key → optional connector pairing.
- **Guide (centrepiece):** set-top-box EPG grid — channel column (logo +
  number), horizontal time axis, virtualised both axes, live "now" line,
  programme cells colour-coded by genre, focus/hover quick-info, click opens the
  **hero overlay**. Full keyboard nav (arrows, PgUp/Dn, `Home` = now), date
  picker, group filter, search. A per-channel clock-shift nudge control mirrors
  tvdinner's `[` / `]`.
- **Channel detail:** one channel, full day/week.
- **Settings:** passkeys list, 2FA, active sessions/devices, email; timezone
  (global + per-source override + per-channel shift); sources CRUD with live
  refresh status; TMDB key; connectors.
- **Hero overlay:** full-bleed backdrop (w1280) at ~55% over a near-black
  ground, title-logo wordmark top-right, ★ rating + TMDB attribution, genres,
  director, top cast, synopsis, now/next, "jump to now", stream-quality pills.
  Pure HTML/CSS/Framer Motion — no server-side image compositing.

Responsive: phone = single-channel vertical agenda + bottom-sheet hero; tablet =
3–4 columns; desktop = full grid. Installable PWA with offline shell. Touch:
horizontal swipe scrubs time, vertical scrolls channels, tap opens hero.
Accessibility: ARIA grid semantics, full keyboard, `prefers-reduced-motion`,
WCAG AA contrast in both themes.

---

## Branding

- **Logo:** build a custom lockup from an MIT/ISC-licensed base glyph —
  [Iconoir](https://iconoir.com) (MIT) or [Lucide](https://lucide.dev) (ISC)
  `tv` / `clapperboard`. Mark = rounded-rect "screen" with a faint scanline and
  a play triangle, filled with the brand gradient. Wordmark "tvtimes" in a
  SIL-OFL geometric sans (Space Grotesk). Ship `logo-mark.svg`,
  `logo-lockup.svg`, favicon set in `frontend/src/assets/brand/`.
- **Colour wash — "twilight aurora":** near-black canvas `#0B0713`; gradient
  deep indigo `#1B0A3D` → electric violet `#6D28D9` → magenta-pink `#DB2777`
  with a warm amber accent `#F59E0B`. Rendered as a large blurred radial
  gradient behind the guide plus a low-opacity film-grain texture. Genre chips
  use a fixed accessible categorical palette. Matching light theme (same hues,
  raised lightness, off-white ground). All values are CSS custom properties in
  `frontend/src/styles/theme.css`; documented in `docs/brand.md`.

---

## Connector (phase 7)

Small Python agent, shipped as a PyInstaller binary + Docker image, run on the
user's LAN. **Outbound HTTPS only** (WebSocket or long-poll to the backend — no
inbound ports).

- **Pair:** Settings → "Add connector" shows an 8-char code →
  `tvtimes-connector --pair CODE --server https://…` exchanges it for a
  long-lived token (encrypted locally) → registers with version + discovery.
- **Run:** periodic HDHomeRun discovery (`discover.json` / `lineup.json`) on the
  LAN → posts lineups → backend materialises them as a `source`; resolves LAN
  stream URLs on demand; can serve local files.
- Backend `api/routers/connector.py` handles pair / heartbeat / lineup /
  resolve.

---

## Build order

1. **Scaffold** — monorepo, `docker-compose.yml`, FastAPI + OpenAPI, Vite app,
   Postgres + Alembic, CI (ruff/black/mypy/eslint/tsc).
2. **Auth** — tenant/user models, email verify, passkey register/login,
   password fallback, rotating sessions, TOTP, settings UI for devices/sessions.
   Run `/security-review`.
3. **Cloud sources** — source CRUD + encrypted config, port
   `m3u`/`xtream`/`stalker` ingest behind `ssrf.py`, `refresh_source` worker,
   `channel` table, status UI.
4. **EPG** — port XMLTV parser, `epg_source` model, conditional GET, `programme`
   rows, programme↔channel matching, timezone + clock-shift resolution.
5. **Guide UI** — virtualised grid, now-line, genre colours,
   date/filter/search, keyboard nav, responsive + PWA, branding + colour wash.
6. **TMDB + hero** — token storage, port + upgrade `tmdb.py`
   (`append_to_response`), `enrich_programme` worker, global cache table, hero
   DTO + cinematic overlay UI, TMDB attribution.
7. **Connector** — agent app, pairing, HDHomeRun discovery + lineup submit,
   stream-resolve proxy.
8. **Polish** — light theme, accessibility audit, rate-limit tuning, load-test
   guide queries, docs.

---

## Verification

- `docker compose up` → API at `:8000/docs`, SPA at `:5173`.
- **Auth:** register a user, verify via console link, add a passkey with
  Chrome DevTools virtual authenticator, log out/in, confirm the refresh cookie
  rotates on `/auth/refresh`, enable TOTP, revoke a session and confirm it dies.
- **Sources:** add a public M3U + its XMLTV; worker fills `channel` +
  `programme`; confirm `ssrf.py` rejects `http://169.254.169.254` and
  `http://192.168.0.10`.
- **Guide:** grid renders with logos and a correct now-line for the chosen tz;
  set a source `timezone_override` and a channel `clock_shift_seconds` and see
  times move; mobile viewport shows the agenda layout.
- **TMDB:** add a real v4 token; a movie-category programme shows
  backdrop/logo/rating/genres/cast in the hero; a non-match shows the plain
  banner with no wrong art; the negative is cached, a forced network failure is
  not.
- **Connector:** pair from Settings, see an HDHomeRun lineup appear as a source.
- **Tests:** `pytest backend/`, `npm --prefix frontend test`, `playwright test`.

## Sources

- [Iconoir (MIT icons)](https://iconoir.com/)
- [Lucide (ISC icons)](https://lucide.dev/)
- [TMDB append_to_response](https://developer.themoviedb.org/docs/append-to-response)
- Ported modules: `/home/iain/projects/tvdinner/src/tvdinner/{m3u,xtream,stalker,hdhomerun,epg,tmdb,channel_logos,redact,movietitle}.py`
