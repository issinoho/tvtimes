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


def test_production_requires_https_origin() -> None:
    with pytest.raises(RuntimeError, match="https"):
        _prod(public_origin="http://tvtimes.issinoho.com").assert_production_ready()


def test_dev_config_is_not_checked() -> None:
    Settings(env="dev").assert_production_ready()  # no raise despite dev defaults
