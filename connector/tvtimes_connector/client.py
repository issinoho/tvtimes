"""HTTP client for the tvtimes connector API (outbound only)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from tvtimes_connector import __version__
from tvtimes_connector.hdhomerun import DeviceLineup


class ConnectorApiError(RuntimeError):
    pass


@dataclass
class PairResult:
    connector_id: str
    token: str
    heartbeat_interval: int


def pair(server: str, code: str) -> PairResult:
    url = f"{server.rstrip('/')}/api/connector/pair"
    try:
        resp = httpx.post(url, json={"code": code.strip().upper()}, timeout=15.0)
    except httpx.HTTPError as exc:
        raise ConnectorApiError(f"Could not reach {server}: {exc}") from exc
    if resp.status_code >= 400:
        detail = _detail(resp)
        raise ConnectorApiError(f"Pairing failed: {detail}")
    body = resp.json()
    return PairResult(
        connector_id=body["connector_id"],
        token=body["token"],
        heartbeat_interval=int(body.get("heartbeat_interval", 60)),
    )


class Session:
    def __init__(self, server: str, token: str) -> None:
        self._base = server.rstrip("/")
        self._client = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def heartbeat(self) -> int:
        resp = self._client.post(
            f"{self._base}/api/connector/heartbeat", json={"version": __version__}
        )
        self._check(resp)
        return int(resp.json().get("heartbeat_interval", 60))

    def submit_lineup(self, lineup: DeviceLineup) -> int:
        payload = {
            "device_id": lineup.device.device_id or lineup.device.base_url,
            "friendly_name": lineup.device.friendly_name,
            "model": lineup.device.model,
            "tuner_count": lineup.device.tuner_count,
            "epg_url": lineup.epg_url,
            "channels": [
                {
                    "name": c.name,
                    "stream_url": c.stream_url,
                    "number": c.number,
                    "hd": c.hd,
                }
                for c in lineup.channels
            ],
        }
        resp = self._client.post(f"{self._base}/api/connector/lineup", json=payload)
        self._check(resp)
        return int(resp.json().get("channels", 0))

    @staticmethod
    def _check(resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise ConnectorApiError("The connector token was rejected. Re-pair this connector.")
        if resp.status_code >= 400:
            raise ConnectorApiError(f"Server returned {resp.status_code}: {_detail(resp)}")


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("message") or body.get("detail") or body)
    except ValueError:
        return resp.text[:200]
