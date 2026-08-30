"""The run loop: discover lineups, push them, heartbeat, repeat."""

from __future__ import annotations

import logging
import time

from tvtimes_connector.client import ConnectorApiError, Session
from tvtimes_connector.config import Config
from tvtimes_connector.hdhomerun import collect_lineups

log = logging.getLogger("tvtimes-connector")

_LINEUP_EVERY = 15 * 60  # re-scan and push lineups at most this often


def run_once(session: Session, config: Config) -> int:
    lineups = collect_lineups(config.devices)
    if not lineups:
        log.warning(
            "no HDHomeRun devices found (UDP discovery + %d configured)", len(config.devices)
        )
        return 0
    total = 0
    for lineup in lineups:
        n = session.submit_lineup(lineup)
        total += n
        log.info("pushed %s: %d channels", lineup.device.friendly_name, n)
    return total


def run_forever(config: Config) -> None:
    if not config.is_paired:
        raise SystemExit("Not paired. Run: tvtimes-connector pair --server <url> --code <code>")

    session = Session(config.server, config.token)
    interval = config.heartbeat_interval
    last_lineup = 0.0
    try:
        while True:
            now = time.monotonic()
            try:
                interval = session.heartbeat()
                if now - last_lineup >= _LINEUP_EVERY:
                    run_once(session, config)
                    last_lineup = now
            except ConnectorApiError as exc:
                log.error("%s", exc)
                if "re-pair" in str(exc).lower():
                    raise SystemExit(str(exc)) from exc
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("unexpected error; retrying")
            time.sleep(max(15, interval))
    finally:
        session.close()
