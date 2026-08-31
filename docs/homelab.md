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
POSTGRES_PASSWORD=pick-something
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
(`TVTIMES_IMAGE=issinoho1969/tvtimes:v1.2.0`) to upgrade deliberately.

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
```

Caddy:

```
tv.example.com {
    reverse_proxy 127.0.0.1:8888
}
```

Nginx: proxy `/` to `127.0.0.1:8888` with `proxy_set_header X-Forwarded-Proto
$scheme;` and `X-Forwarded-For`. The app already trusts forwarded headers.

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

## Troubleshooting

- **"insecure production config" on start** — you set your own
  `TVTIMES_ENCRYPTION_KEY`/`TVTIMES_JWT_PRIVATE_KEY_PEM` to a placeholder.
  Unset them and let the container generate them, or provide real values.
- **Passkey registration fails** — `TVTIMES_PUBLIC_ORIGIN` doesn't match the
  address bar, or `TVTIMES_WEBAUTHN_RP_ID` isn't the origin's domain.
- **Worker idle / guide not filling** — check `docker compose logs worker` and
  that `redis` is healthy.
- **HDHomeRun source errors with "not a private LAN address"** — the address
  must resolve to an RFC1918 range (`10.`, `172.16–31.`, `192.168.`).
- **M3U / Xtream / XMLTV URL rejected: "resolves to a non-public address"** —
  the guard blocks LAN targets by default. If it's a service on your own
  network (a Pluto proxy, xTeVe/Threadfin, another box), allow it:
  `TVTIMES_FETCH_ALLOWLIST=192.168.0.218` (or a CIDR like `192.168.0.0/24`),
  then `docker compose up -d --force-recreate`.
