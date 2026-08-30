# tvtimes connector

The **connector** is a small agent you run on your home network so tvtimes can
reach LAN-only sources — HDHomeRun tuners and local media files — that a hosted
service cannot see directly.

- Outbound HTTPS only; no inbound ports to open.
- Pairs to your account with a short code, then reports discovered devices and
  proxies stream-URL resolution.

**Not built yet** — this is phase 7 (see [`../docs/plan.md`](../docs/plan.md)).
Cloud sources (remote M3U / Xtream / Stalker / XMLTV URLs) work without it.
