# Security Policy

## Supported versions

tvtimes is released as rolling `v*` tags. Only the **latest** published image
(`issinoho1969/tvtimes:latest` / the highest `v*` tag) is supported — fixes go
into a new release, not backports.

| Version | Supported |
|---------|-----------|
| latest `v*` | ✅ |
| older tags | ❌ (upgrade) |

## Reporting a vulnerability

**Do not open a public issue for security problems.**

- Preferred: GitHub → **Security → Report a vulnerability** (private advisory) on
  <https://github.com/issinoho/tvtimes/security/advisories/new>.
- Or email **iain@issinoho.com** with `tvtimes security` in the subject.

Please include a description, affected version/commit, reproduction steps, and
the impact you see. A proof-of-concept helps; a working exploit isn't required.

What to expect:

- Acknowledgement within **5 days**.
- An assessment and a fix timeline once triaged; typically a patched release
  within **30 days** for confirmed high-severity issues.
- Credit in the release notes / advisory unless you'd rather stay anonymous.

## Scope

In scope: the backend API, the SPA, the connector agent, the container image and
its entrypoint, the published `docker-compose.yml`.

Out of scope: issues that require a compromised host or a malicious operator
(they already control the secrets); vulnerabilities in third-party base images or
dependencies with no tvtimes-specific exposure (report those upstream); findings
that only apply when the documented hardening is ignored (running on plain HTTP
outside a trusted LAN, reusing the insecure default keys, etc.).

## Design notes for reviewers

- All outbound fetches for user-supplied URLs go through `app/ingest/ssrf.py`
  (rejects loopback/private/link-local/CGNAT, re-checks redirects, size-caps).
  The one intentional exception is native HDHomeRun, which *requires* a private
  LAN address.
- Secrets at rest (source credentials, TOTP seeds, TMDB token, connector token)
  are Fernet-encrypted; the signing and encryption keys are generated into a
  volume on first run.
- Auth: passkeys-first WebAuthn, Argon2id + HIBP password fallback, TOTP,
  EdDSA access JWTs (15 min) + rotating opaque refresh tokens with replay
  detection, double-submit CSRF on the cookie-authed routes.
