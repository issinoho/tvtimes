"""``tvtimes-connector`` — pair, run, status."""

from __future__ import annotations

import argparse
import logging
import sys

from tvtimes_connector import __version__
from tvtimes_connector import client as api
from tvtimes_connector.agent import run_forever, run_once
from tvtimes_connector.client import Session
from tvtimes_connector.config import Config, config_path
from tvtimes_connector.hdhomerun import collect_lineups


def _cmd_pair(args: argparse.Namespace) -> int:
    result = api.pair(args.server, args.code)
    config = Config.load()
    config.server = args.server.rstrip("/")
    config.connector_id = result.connector_id
    config.token = result.token
    config.heartbeat_interval = result.heartbeat_interval
    config.save()
    print(f"Paired. Config written to {config_path()}")
    print("Now run:  tvtimes-connector run")
    return 0


def _cmd_run(_args: argparse.Namespace) -> int:
    run_forever(Config.load())
    return 0


def _cmd_scan(_args: argparse.Namespace) -> int:
    config = Config.load()
    lineups = collect_lineups(config.devices)
    if not lineups:
        print("No HDHomeRun devices found.")
        return 1
    for lineup in lineups:
        dev = lineup.device
        print(f"{dev.friendly_name} ({dev.base_url}): {len(lineup.channels)} channels")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    config = Config.load()
    print(f"config:   {config_path()}")
    print(f"server:   {config.server or '(not paired)'}")
    print(f"paired:   {'yes' if config.is_paired else 'no'}")
    if config.devices:
        print(f"devices:  {', '.join(config.devices)}")
    if config.is_paired:
        try:
            session = Session(config.server, config.token)
            interval = session.heartbeat()
            n = run_once(session, config)
            session.close()
            print(f"heartbeat OK (interval {interval}s); pushed {n} channels")
        except Exception as exc:  # noqa: BLE001
            print(f"heartbeat FAILED: {exc}")
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tvtimes-connector", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pair", help="claim a pairing code from the tvtimes UI")
    p.add_argument("--server", required=True, help="e.g. https://tvtimes.issinoho.com")
    p.add_argument("--code", required=True)
    p.set_defaults(func=_cmd_pair)

    sub.add_parser("run", help="run the agent loop (heartbeat + lineup push)").set_defaults(
        func=_cmd_run
    )
    sub.add_parser("scan", help="list HDHomeRun devices seen on this network").set_defaults(
        func=_cmd_scan
    )
    sub.add_parser("status", help="show config and test the server connection").set_defaults(
        func=_cmd_status
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc.code, file=sys.stderr)
        return int(exc.code) if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
