# Self-hosting tvtimes

tvtimes is one Docker Compose stack: an all-in-one app container (API + worker +
web UI), Postgres, and Redis. No build step — it runs a published image.

## 1. Get the files

```sh
mkdir tvtimes && cd tvtimes
curl -O https://raw.githubusercontent.com/issinoho/tvtimes/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/issinoho/tvtimes/main/.env.example
```

## 2. Configure

Edit `.env`. For a first run on your LAN you only need:

```sh
TVTIMES_PUBLIC_ORIGIN=http://192.168.1.10:8888   # the address you'll open in a browser
TVTIMES_WEBAUTHN_RP_ID=localhost                  # keep as localhost for a bare-IP setup
POSTGRES_PASSWORD=          # required; e.g. `openssl rand -hex 24`
```

`TVTIMES_PUBLIC_ORIGIN` must match exactly what the browser shows — scheme,
host, and port. Passkeys are bound to it.

## 3. Start

```sh
docker compose up -d
docker compose logs -f tvtimes
```

Open `TVTIMES_PUBLIC_ORIGIN` and create your account. With
`TVTIMES_EMAIL_PROVIDER=console` (the default) the verification link is printed
in the log above — click it from there.

## 4. Upgrades

```sh
docker compose pull
docker compose up -d --force-recreate
```

Migrations run automatically on start. `--force-recreate` ensures the running
containers move onto the freshly pulled image (a bare `up -d` sometimes reports
"Running" and does nothing). A browser tab that's already open shows a "new
version available — Reload" prompt. Pin a version in `.env`
(`TVTIMES_IMAGE=issinoho1969/tvtimes:0.1.53`) to upgrade deliberately — note the
image tag has **no leading `v`**, unlike the git tag it's built from. `0.1`
tracks the newest patch on that line.

## Data & backups

Three named volumes hold everything:

| Volume | Contents |
|--------|----------|
| `tvtimes_pgdata` | Postgres — accounts, sources, guide data |
| `tvtimes_redisdata` | queue + caches (safe to lose) |
| `tvtimes_secrets` | the generated signing / encryption keys — **back this up** |

If `tvtimes_secrets` is lost, every saved source credential and TOTP secret
becomes unreadable and all sessions drop. Back up Postgres with:

```sh
docker compose exec db pg_dump -U tvtimes tvtimes | gzip > tvtimes-$(date +%F).sql.gz
```

## Running behind a reverse proxy (HTTPS)

Passkeys and `Secure` cookies need HTTPS (or `localhost`). Terminate TLS at your
proxy and send everything to the app container. Set in `.env`:

```sh
TVTIMES_PUBLIC_ORIGIN=https://tv.example.com
TVTIMES_WEBAUTHN_RP_ID=tv.example.com
# The proxy's address as the app container sees it — so tvtimes trusts the
# X-Forwarded-For it sets. Without this, rate limits and the audit log see the
# proxy's IP for every request. The compose default network is 172.16.0.0/12;
# a same-host proxy is 127.0.0.1.
TVTIMES_TRUSTED_PROXIES=172.16.0.0/12
```

Caddy:

```
tv.example.com {
    reverse_proxy 127.0.0.1:8888
}
```

Nginx: proxy `/` to `127.0.0.1:8888` with `proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for;`.

**`X-Forwarded-For` is trusted only from `TVTIMES_TRUSTED_PROXIES`.** A request
that arrives directly (no proxy configured, or from an address not in that
list) is attributed to its real TCP peer and its `X-Forwarded-For` is ignored,
so it can't spoof its IP to get around a login/registration rate limit or write
a fake address into the audit log.

## HDHomeRun tuners

Add a source, choose **HDHomeRun**:

- **Same network as the server, not in Docker's bridge:** leave the address
  blank to auto-discover.
- **tvtimes running in Docker (the usual case):** the default bridge network
  can't receive discovery broadcasts — enter the tuner's address, e.g.
  `http://192.168.1.50`. Find it at <https://my.hdhomerun.com> or your router.
- **Tuner on a different network from the server:** run the connector there
  (`docker run --network host issinoho1969/tvtimes-connector run --pair <code>
  --server https://tv.example.com`) and pair it from **Settings → Connectors**.

The SiliconDust guide data (`api.hdhomerun.com`) is picked up automatically when
the tuner reports a DeviceAuth.

## A source with channels but no guide

Most M3U playlists advertise their XMLTV feed (`x-tvg-url`) and tvtimes adopts it
automatically. Some (a few Pluto proxies) don't, leaving the source with an empty
guide. Open the source's **EPG** panel and paste an XMLTV URL (`.xml` or
`.xml.gz`) into **Attach XMLTV** — it's matched tenant-wide across all channels,
and you can remove it again from the same panel. A LAN URL you've added to
`TVTIMES_FETCH_ALLOWLIST` is accepted here too.

## Finding something to watch

You land on **Tonight**: a card for every channel that's on air now (with what's
on next), a row of films starting in the next few hours, and — if TMDB is
connected — the highest-rated films across the coming week. Every card opens the
programme panel. The full grid is one click away under **Guide**.

The **Search** page matches programme titles across every channel for the next
two weeks, in the guide's channel order. From a Tonight card, a search result, or
any programme's info panel, pick **Remind me** for that single airing or **Watch
this title** to be mailed before every future showing (see Email, below).

## Use tvtimes as your playlist / EPG provider

tvtimes can hand your whole line-up to another player — Jellyfin, Plex, Emby,
TiviMate, Threadfin — as one merged **M3U playlist** and **XMLTV guide**. Every
enabled source is combined and de-duplicated, and programme times are written
already corrected for each channel's timezone and clock offset, so the
downstream guide needs no further fixing.

1. **Settings → Export feeds → Generate feed links.**
2. Copy the two URLs. They carry a secret token and are shown **once** — rotate
   any time to get fresh links (the old ones stop working), or Disable to switch
   the feeds off entirely.

```
https://tv.example.com/api/exports/playlist.m3u?token=…
https://tv.example.com/api/exports/epg.xml?token=…
```

In **Jellyfin** → *Live TV* → add an **M3U Tuner** with the playlist URL, then an
**XMLTV** guide source with the EPG URL. Plex (*Live TV & DVR* → "have an XMLTV
guide") and TiviMate (add playlist → *Xtream/M3U* → external EPG) work the same
way.

For [tvdinner](https://github.com/issinoho/tvdinner) there's a third row on that
panel — **Open in tvdinner** — carrying a single `tvtimess://tv.example.com?token=…`
URL that stands in for both feeds. Click it (once tvdinner has run
`tvdinner default-handler`) and it opens straight there; or copy it and run
`tvdinner 'tvtimess://…'`. tvdinner expands it back into the same playlist +
guide pair, so its own program guide, recording and scheduling all work against
your merged line-up.

**Recording straight from your watchlist.** The same token also serves
`/api/exports/watchlist.json` — every upcoming airing anyone on the account has
watchlisted, with corrected times and the same `/stream/<id>` URLs the M3U uses.
Run tvdinner with `--record-watchlist` and it polls that feed every 15 minutes,
scheduling a recording for each one:

```sh
tvdinner 'tvtimess://tv.example.com?token=…' --record-watchlist
```

Press **Remind me** on your phone and the box at home records it. The watchlist
is per user while the token is per account, so a shared household account
records what *anyone* on it flagged, de-duplicated per broadcast.
Un-watchlisting removes the pending recording again; anything scheduled by hand
in tvdinner is left alone.

**Seeing what you've watched.** Run tvdinner with `--report-watch-state` and it
posts what you actually watched back every 15 minutes, to
`/api/exports/watch-events`; the guide grid then dims and ticks those
programmes:

```sh
tvdinner 'tvtimess://tv.example.com?token=…' --report-watch-state --device-name 'living room'
```

What's sent is plain start/stop **intervals**, not "programme X was watched" —
tvtimes derives which programmes those cover by overlapping them against its own
guide. So a guide refresh, or correcting a channel's clock offset, updates the
answer with nothing re-reported. A programme counts as watched once half of it,
or 30 minutes, is covered; flicking past doesn't.

This is the **one thing the export token can write**. It can only append
intervals for channels already on your account, so a leaked token can at worst
pollute your own watched badges — it already exposes the whole line-up and
streams through it. If that's not a trade you want, leave
`--report-watch-state` off and nothing is ever written.

**Sharing favourites.** `/api/exports/favourites.json` lists the channels anyone
on the account has starred. `tvdinner --sync-favourites` picks those up at
startup, so a star set here shows in its guide too. It's additive and one-way:
un-starring here won't un-star it there, because tvdinner records favourites by
name with no note of where each came from — quietly deleting one you'd set
locally is the worse failure.

**Jumping back the other way.** Pressing `T` in tvdinner opens tvtimes for
whatever's on the current channel. It lands on `/search?q=<title>` rather than
the exact guide cell — the grid is virtualised, so pointing at one cell would
need scroll-to-row support, and arriving from a player what you want is to find
the thing by name. Any app can use the same URL; the search box picks `q` up as
its starting text and then drops it from the address bar, so a reload or a
bookmark doesn't re-run a search you've since typed over.

The full pairing story — all five capabilities, why each is shaped the way it
is, and what the token reaches — is on the wiki:
[Pairing with tvdinner](https://github.com/issinoho/tvtimes/wiki/Pairing-With-tvdinner).

Notes:

- Anyone with a link can read your line-up and stream through it — treat the
  URLs as passwords. Rotating invalidates the previous token.
- The export API has a published OpenAPI reference:
  <https://issinoho.github.io/tvtimes/api/> (the document itself is at
  `api/openapi.json`, if you'd rather point a client generator at it). It covers
  the playlist, guide, watchlist, favourites, watch-events and stream routes,
  and both auth schemes. The rest of the API is the web app's own and isn't
  documented — it may change in any release.
- **Settings → Export feeds** shows when the feeds were last fetched, and lists
  the players reporting watch state back (by `--device-name`, or grouped as
  "Unlabelled player" for one running without it). That's the only place a
  paired player is visible: an export token never creates an entry on the
  Sessions screen, and a watchlist or favourites poll is a plain read. Use it to
  tell whether a box is still talking to you, or whether a token you'd forgotten
  about is still in use.
- Channels are keyed by their tvtimes id, so an East/West pair that shares a
  tvg-id upstream still links to the right guide data downstream.
- Playback is proxied per channel through `/api/exports/stream/<id>` — the URL
  302-redirects to the real stream (Xtream credentials stay on the server and
  never appear in the file). **Stalker portal** channels appear in the guide but
  don't play through the export yet.

## Play a channel in your device's player

To just watch one channel now — without wiring up a whole tuner — open a
programme in the guide and press **Play**. tvtimes hands the channel to a
media app; it does not play video in the browser itself.

- **Desktop** — **Play** opens a `tvdinner:` link, which
  [tvdinner](https://github.com/issinoho/tvdinner) picks up directly (run
  `tvdinner default-handler` once): nothing is saved and there's no
  application picker. For any other player, use **Download .m3u** and open
  the file — associate `.m3u` with VLC/mpv on Linux
  (`xdg-mime default vlc.desktop audio/x-mpegurl`) or PotPlayer/MPC on
  Windows.
- **Android** — an app chooser appears (tick "always" to skip it next time).
  Firefox for Android falls back to the `.m3u` download.
- **Copy stream URL** gives you the raw address to paste into VLC's *Open
  Network Stream* or any other player.

The downloaded `.m3u` also carries a `url-tvg=` link to that one channel's
XMLTV, so a player that reads it (tvdinner, TiviMate, …) shows the guide for
the channel too — no separate EPG setup.

The play link is single-channel and expires after 24 hours — long enough to
open a `.m3u` you saved earlier, but, unlike the export token, not a standing
secret, and it needs no export feed enabled.
**Stalker portal** channels can't produce a static URL, so Play is unavailable
for them (same limitation as the export feed above).

## Email (optional but recommended)

`console` is fine for a single account. For real delivery set in `.env`:

```sh
TVTIMES_EMAIL_PROVIDER=smtp
TVTIMES_EMAIL_FROM=tvtimes <tv@example.com>
TVTIMES_SMTP_HOST=smtp.example.com
TVTIMES_SMTP_PORT=587
TVTIMES_SMTP_USERNAME=...
TVTIMES_SMTP_PASSWORD=...
```

or `TVTIMES_EMAIL_PROVIDER=resend` with `TVTIMES_RESEND_API_KEY`.

Email also carries **watchlist reminders** — open a programme from the guide or
search and pick *Remind me* (that airing) or *Watch this title* (every future
airing). The worker emails you ~15 minutes before, to your verified account
address.

It also sends a **source-health alert** when one of your sources breaks, goes
stale (stops refreshing) or recovers — one email per transition, to every
verified account on the tenant.

With `console` these are only written to the worker log, so set a real provider
if you want them to actually arrive.

### Push notifications

Independently of email, **Settings → Push notifications** takes any number of
[Apprise](https://github.com/caronc/apprise) URLs — Gotify, ntfy, Discord,
Telegram, Pushover and ~100 other services behind one URL scheme. Each target
can be toggled for source-health alerts and watchlist reminders separately, and
the same events fan out to every enabled target alongside email. The URL is
stored encrypted (it usually carries a token) and only ever shown back
redacted; **Test** sends a one-off to check it. Delivery is fail-open — a dead
target is logged and skipped, never blocking the others or the email path.
Targets are outbound-only and *not* subject to the SSRF guard, so a
LAN address like `gotify://192.168.1.10/…` is fine.

### Activity notifications

**Settings → Activity notifications** adds four push-only opt-ins that fire when
someone on the account acts: a **reminder is set** on a programme, a **title is
added** to the watchlist, a **channel is played**, or a **watchlist entry is
removed**. Each is a separate account-wide toggle, off by default. Unlike the
per-target flags above these ignore the per-target toggles — when a category is
on it fans out to *every* enabled target. There is no email for these, and the
push is queued so it never adds latency to the click that triggered it.

The **channel is played** push names whatever is on air at that moment (from the
guide, clock-shift corrected) and includes its TMDB poster where the enrichment
cache has one: as a real attachment on notifiers that support one (ntfy, Discord,
Telegram, Pushover, …), and as an inline markdown image on Gotify (which drops
Apprise attachments but renders markdown). With no guide data it falls back to
just the channel name.

## Troubleshooting

- **"insecure production config" on start** — you set your own
  `TVTIMES_ENCRYPTION_KEY`/`TVTIMES_JWT_PRIVATE_KEY_PEM` to a placeholder.
  Unset them and let the container generate them, or provide real values.
- **Passkey registration fails** — `TVTIMES_PUBLIC_ORIGIN` doesn't match the
  address bar, or `TVTIMES_WEBAUTHN_RP_ID` isn't the origin's domain.
- **Worker idle / guide not filling** — check `docker compose logs worker` and
  that `redis` is healthy.
- **`PermissionError: … '/data/…'` in a crash loop** — `/data` is a bind mount
  the container's user can't write to. The entrypoint normally fixes this
  itself; you'll only see it if you've set a `user:` override in compose. Then
  `chown` the host directory to that uid and restart.
- **HDHomeRun source errors with "not a private LAN address"** — the address
  must resolve to an RFC1918 range (`10.`, `172.16–31.`, `192.168.`).
- **M3U / Xtream / XMLTV URL rejected: "resolves to a non-public address"** —
  the guard blocks LAN targets by default. If it's a service on your own
  network (a Pluto proxy, xTeVe/Threadfin, another box), allow it:
  `TVTIMES_FETCH_ALLOWLIST=192.168.0.218` (or a CIDR like `192.168.0.0/24`),
  then `docker compose up -d --force-recreate`.
