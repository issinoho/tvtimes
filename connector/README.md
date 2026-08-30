# tvtimes connector

A small agent you run on your home network so tvtimes can use **HDHomeRun**
tuners it can't reach directly. It only makes **outbound HTTPS** calls — nothing
listens for inbound connections, no ports to open.

> If the tvtimes server is on the **same network** as the tuner, you don't need
> this — add a native **HDHomeRun** source instead (Settings → Sources). The
> connector is for tuners on a different network from the server.

## Install

Requires Python 3.10+.

```sh
pipx install tvtimes-connector      # or: pip install --user tvtimes-connector
```

or run it in Docker:

```sh
docker run --network host -v tvtimes-connector:/config \
  -e TVTIMES_CONNECTOR_CONFIG=/config/config.json \
  issinoho1969/tvtimes-connector run          # or ghcr.io/issinoho/tvtimes-connector
```

(`--network host` lets it see HDHomeRun devices on your LAN.)

## Pair

In tvtimes → **Settings → Connectors → Add connector**, then:

```sh
tvtimes-connector pair --server https://tvtimes.issinoho.com --code ABCD1234
tvtimes-connector run
```

The config (server, connector id, token) is written to
`~/.config/tvtimes-connector/config.json` (mode 600).

## Commands

| | |
|---|---|
| `pair --server <url> --code <code>` | claim a pairing code |
| `run` | the agent loop: heartbeat + push HDHomeRun lineups |
| `scan` | list HDHomeRun devices seen on this network |
| `status` | show config and test the server connection |

If UDP discovery is blocked on your network, add device base URLs to the config:

```json
{ "server": "…", "token": "…", "devices": ["http://192.168.1.50"] }
```

## What it sends

Per device: the friendly name, model, tuner count, its channel lineup
(`GuideNumber`, `GuideName`, stream URL, HD flag), and — if the device has a
SiliconDust DVR subscription — the cloud XMLTV URL for the programme guide.
Stream URLs are LAN addresses; playback from them needs a client on the same
network.
