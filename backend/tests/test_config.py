from __future__ import annotations

import pytest
from app.config import Settings


def _prod(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "prod",
        "jwt_private_key_pem": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----",
        "encryption_key": "a-real-looking-key",
        "public_origin": "https://tvtimes.issinoho.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_production_config_ok() -> None:
    _prod().assert_production_ready()  # no raise


def test_production_rejects_missing_jwt_key() -> None:
    with pytest.raises(RuntimeError, match="JWT_PRIVATE_KEY"):
        _prod(jwt_private_key_pem="").assert_production_ready()


def test_production_rejects_default_encryption_key() -> None:
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        _prod(encryption_key="dev-insecure-key-abc").assert_production_ready()


def test_production_warns_but_allows_http_origin(capsys: pytest.CaptureFixture[str]) -> None:
    # Self-hosters often terminate TLS at their own reverse proxy, so a plain
    # http:// origin is a warning, not a hard failure.
    _prod(public_origin="http://tvtimes.lan").assert_production_ready()
    assert "https" in capsys.readouterr().err.lower()


def test_dev_config_is_not_checked() -> None:
    Settings(env="dev").assert_production_ready()  # no raise despite dev defaults


def test_database_url_scheme_is_normalised() -> None:
    assert (
        Settings(database_url="postgres://u:p@h:5432/db").database_url
        == "postgresql+asyncpg://u:p@h:5432/db"
    )
    assert (
        Settings(database_url="postgresql://u:p@h/db").database_url
        == "postgresql+asyncpg://u:p@h/db"
    )
    assert Settings(database_url="sqlite+aiosqlite:///./x.db").database_url.startswith("sqlite")
