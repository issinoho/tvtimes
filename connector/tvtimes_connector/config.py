"""Local config: the paired server, connector id and token, plus any
manually-specified HDHomeRun device URLs."""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def config_path() -> Path:
    base = os.environ.get("TVTIMES_CONNECTOR_CONFIG")
    if base:
        return Path(base)
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "tvtimes-connector" / "config.json"


@dataclass
class Config:
    server: str = ""
    connector_id: str = ""
    token: str = ""
    heartbeat_interval: int = 60
    # Optional explicit device base URLs (e.g. "http://192.168.1.50") for
    # networks where UDP discovery is blocked.
    devices: list[str] = field(default_factory=list)

    @property
    def is_paired(self) -> bool:
        return bool(self.server and self.token)

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        with contextlib.suppress(OSError):
            path.chmod(0o600)
