from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from tvtimes_connector.client import ConnectorApiError, Session, pair
from tvtimes_connector.config import Config, config_path


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TVTIMES_CONNECTOR_CONFIG", str(tmp_path / "config.json"))


def test_config_roundtrip_and_permissions() -> None:
    assert Config.load().is_paired is False
    cfg = Config(server="https://x", connector_id="c1", token="t", devices=["http://10.0.0.9"])
    cfg.save()

    loaded = Config.load()
    assert loaded.is_paired
    assert loaded.token == "t"
    assert loaded.devices == ["http://10.0.0.9"]
    assert oct(config_path().stat().st_mode)[-3:] == "600"


def test_config_ignores_unknown_keys(tmp_path: Path) -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text('{"server": "https://x", "token": "t", "bogus": 1}')
    assert Config.load().server == "https://x"


@respx.mock
def test_pair_success_and_failure() -> None:
    respx.post("https://srv/api/connector/pair").mock(
        return_value=httpx.Response(
            200, json={"connector_id": "c1", "token": "tok", "heartbeat_interval": 30}
        )
    )
    result = pair("https://srv", "abcd1234")
    assert result.token == "tok"
    assert result.heartbeat_interval == 30

    respx.post("https://srv/api/connector/pair").mock(
        return_value=httpx.Response(400, json={"message": "expired"})
    )
    with pytest.raises(ConnectorApiError, match="expired"):
        pair("https://srv", "nope")


@respx.mock
def test_session_rejected_token_asks_to_repair() -> None:
    respx.post("https://srv/api/connector/heartbeat").mock(return_value=httpx.Response(401))
    session = Session("https://srv", "bad")
    with pytest.raises(ConnectorApiError, match="Re-pair"):
        session.heartbeat()
    session.close()
