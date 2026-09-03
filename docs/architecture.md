# How the pieces fit

Where your channels and guide data come from, what tvtimes does with them, and
how they reach the thing you actually watch on.

- [The whole path](#the-whole-path) — end to end, in one picture
- [The video never passes through tvtimes](#the-video-never-passes-through-tvtimes) — why the playlist points at us but the bytes don't
- [Getting sources in](#getting-sources-in) — the five source kinds, and the connector
- [How tvtimes and tvdinner cooperate](#how-tvtimes-and-tvdinner-cooperate) — the pairing, and why it's shaped that way
- [tvdinner on its own](#tvdinner-on-its-own) — it doesn't need tvtimes

---

## The whole path

```mermaid
flowchart LR
    subgraph UP["Upstream — where the data comes from"]
        direction TB
        PROV["IPTV provider<br/><i>M3U · Xtream · Stalker</i>"]
        M3U4U["m3u4u<br/><i>merged / tidied M3U</i>"]
        EPGB["EPG.best<br/><i>XMLTV guide</i>"]
        FAST["FastChannels<br/><i>self-hosted M3U + XMLTV</i>"]
        HDHR["HDHomeRun tuner<br/><i>aerial / cable</i>"]
        TMDB["TMDB<br/><i>artwork · cast · ratings</i>"]
    end

    subgraph TT["tvtimes — the server you host"]
        direction TB
        WORK["Worker<br/><i>scheduled refresh</i>"]
        DB[("Postgres<br/><i>channels · guide · watch state</i>")]
        API["API + web app"]
        WORK --> DB --> API
    end

    subgraph CL["Clients"]
        direction TB
        BROWSE["Browser<br/><i>plan: guide, search, watchlist</i>"]
        TVD["tvdinner<br/><i>watch: desktop player</i>"]
        TUNER["Jellyfin · Plex · Emby<br/>TiviMate · Threadfin<br/><i>watch</i>"]
    end

    NOTIF["Gotify · ntfy · Discord · email"]

    PROV & M3U4U & EPGB & FAST & HDHR --> WORK
    TMDB -.->|"films only"| WORK

    API --> BROWSE
    API -->|"export token:<br/>playlist + guide"| TVD & TUNER
    API -->|"reminders · alerts"| NOTIF
```

The browser is where you **plan** — tvtimes has no in-browser player, by
design. Playing happens in tvdinner or whichever tuner app you point at the
feeds.

### The video never passes through tvtimes

The playlist tvtimes hands out points every channel back at *itself*, which
looks like proxying. It isn't:

```mermaid
sequenceDiagram
    autonumber
    participant P as Player<br/>(tvdinner, Jellyfin…)
    participant TT as tvtimes
    participant UP as Provider

    P->>TT: GET /api/exports/stream/{channel_id}?token=…
    Note over TT: looks the channel up,<br/>resolves it against the source
    TT-->>P: 302 → the provider's real URL
    P->>UP: GET that URL
    UP-->>P: the video, direct
    Note over P,UP: tvtimes is not in this path
```

Two consequences worth knowing. Your provider credentials — an Xtream login,
say — **stay on the server** and never appear in a file you hand to a tuner. And
tvtimes needs no bandwidth for playback: it decides *what* you can watch, then
gets out of the way.


---

## Getting sources in

Everything upstream arrives as one of two things: a **playlist** of channels, or
an **XMLTV guide**. A source can carry both — most M3U playlists name their own
guide in a `url-tvg=` attribute — or you can add a guide separately and let
tvtimes match it up.

```mermaid
flowchart LR
    subgraph KINDS["The five source kinds"]
        direction TB
        K1["<b>m3u</b><br/><i>m3u4u · FastChannels ·<br/>a provider link · a local file</i>"]
        K2["<b>xtream</b><br/><i>panel login — brings its<br/>own EPG and VOD API</i>"]
        K3["<b>stalker</b><br/><i>portal + MAC — guide only,<br/>no export yet</i>"]
        K4["<b>hdhomerun</b><br/><i>tuner tvtimes can reach</i>"]
        K5["<b>connector</b><br/><i>tuner it can't</i>"]
    end

    XML["Standalone XMLTV<br/><i>EPG.best, or a provider's guide,<br/>added on its own</i>"]

    subgraph W["Worker — on a schedule"]
        direction TB
        RS["refresh_source<br/><i>pull the channel list</i>"]
        RE["refresh_epg_source<br/><i>pull XMLTV, ETag-aware<br/>so an unchanged guide is free</i>"]
        EN["enrich_epg<br/><i>films → TMDB</i>"]
    end

    K1 --> RS
    K2 --> RS
    K3 --> RS
    K4 --> RS
    K5 --> RS
    RS -.->|"a playlist naming its own<br/>guide in url-tvg"| RE
    XML --> RE

    RS --> DB[("Postgres")]
    RE --> DB
    DB <--> EN
```

**The connector** is the odd one out. It's a small agent you run on the network
where the tuner lives, for when tvtimes itself is somewhere else:

```mermaid
flowchart LR
    TT["tvtimes<br/><i>wherever you host it</i>"]
    CONN["tvtimes connector<br/><i>agent on your home network</i>"]
    HDHR["HDHomeRun tuner"]

    CONN -->|"① outbound HTTPS —<br/>nothing listens, no ports opened"| TT
    TT -.->|"② work handed back<br/>on that same connection"| CONN
    CONN --> HDHR
    HDHR -.->|"③ channels and guide"| CONN
```

The direction of arrow ① is the whole point: the connector dials out, so your
router needs no port forwarding and nothing on your home network is exposed. If
tvtimes is on the *same* network as the tuner you don't need it at all — use a
plain `hdhomerun` source.


Two details that explain most of tvtimes' behaviour:

- **Channels are keyed by tvtimes' own UUID**, not by the upstream `tvg-id`.
  Providers routinely give an East and West feed the same id; keying on our own
  means a programme still links to exactly one channel downstream.
- **Clock correction is applied on the way out**, not stored. A guide that runs
  an hour off gets a per-channel shift, and every export writes times already
  corrected with the right `+ZZZZ` offset — so nothing downstream has to know.

---

## How tvtimes and tvdinner cooperate

tvtimes is where you plan. tvdinner is where you watch. Everything below rides
the **one export token** — there's no second credential and no per-feature
pairing.

```mermaid
sequenceDiagram
    autonumber
    participant You
    participant TT as tvtimes
    participant TD as tvdinner

    Note over TT,TD: One export token covers all of this

    You->>TT: Watchlist a film (phone, browser)
    TD->>TT: GET watchlist.json (every 15 min)
    TT-->>TD: upcoming airings, times already corrected
    Note over TD: schedules a recording

    You->>TD: Watch a channel
    TD->>TT: POST watch-events (every 15 min)
    Note over TT: derives which programmes<br/>those intervals covered
    TT-->>You: guide dims and ticks what you've seen

    You->>TT: Star a channel
    TD->>TT: GET favourites.json (at startup)
    TT-->>TD: starred channels

    You->>TT: Press Play on a programme
    TT-->>TD: tvdinner: link (one channel, 24h ticket)

    You->>TD: Press T on a channel
    TD-->>TT: opens /search?q=<title>
```

### Why it's shaped this way

| Decision | Reason |
|---|---|
| tvdinner reports **intervals**, not "programme X watched" | An EPG re-ingest replaces every programme row. An interval doesn't care, and a clock correction retroactively fixes what counts as watched. |
| Favourites sync is **one-way and additive** | tvdinner stores favourites by name with no record of origin, so a two-way reconcile couldn't tell "removed upstream" from "added here" — and deleting one you set yourself is the worse failure. |
| `T` opens **search**, not the exact guide cell | tvtimes' grid is virtualised, so targeting a cell needs scroll-to-row support. Arriving from a player, finding it by name is what you want anyway. |
| Watchlist recordings are **provenance-marked** | Recordings you scheduled by hand in tvdinner are never touched by the sync. |

### What each credential reaches

| | Reach | Lifetime |
|---|---|---|
| **Export token** | whole line-up, streams, watchlist, favourites; **writes** watch state | until rotated |
| **Play ticket** | one channel and its guide | 24 hours |

`POST /api/exports/watch-events` is the only **write** the export token permits,
and it stays narrow: it appends viewing intervals for channels already on the
account and nothing else.

---

## tvdinner on its own

tvdinner doesn't need tvtimes. It takes the same upstream kinds directly, plus a
few tvtimes has no concept of:

```mermaid
flowchart LR
    subgraph SRC["What tvdinner can open"]
        direction TB
        S1["M3U / M3U8"]
        S2["Xtream panel"]
        S3["Stalker portal"]
        S4["HDHomeRun"]
        S5["tvtimes account<br/><i>tvtimes://</i>"]
        S6["Plex server"]
        S7["Local file · YouTube"]
    end

    TD["tvdinner"]
    SRC --> TD

    TD --> PLAY["mpv playback<br/><i>+ on-screen guide</i>"]
    TD --> REC["Recordings on disk"]
    TD --> CAST["Chromecast"]
```

A `tvtimes://` URL is sugar rather than a new protocol: tvdinner expands it back
into the same `playlist.m3u` + `epg.xml` pair, so the guide, favourites,
recording and scheduling all behave exactly as they would for any M3U + XMLTV
source.

---

## See also

- **[This page, rendered](https://issinoho.github.io/tvtimes/architecture/)** — same content, on the website

- [Export feeds](https://github.com/issinoho/tvtimes/wiki/Export-Feeds) — turning the feeds on
- [Pairing with tvdinner](https://github.com/issinoho/tvtimes/wiki/Pairing-With-tvdinner) — the whole pairing, end to end
- [Export API reference](https://issinoho.github.io/tvtimes/api/) — the routes, as OpenAPI
- [Self-hosting guide](homelab.md) — running it
