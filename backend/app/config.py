"""Application settings, loaded from environment (prefix ``TVTIMES_``)."""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TVTIMES_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = "dev"
    log_level: str = "INFO"

    # Public origin the SPA is served from — used as the WebAuthn origin and to
    # scope the refresh cookie. In prod: https://tvtimes.issinoho.com
    public_origin: str = "http://localhost:5173"
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "tvtimes"

    # Persistence. Unset -> local SQLite file (dev/test convenience only;
    # several columns need Postgres in real deployments).
    database_url: str = "sqlite+aiosqlite:///./tvtimes.sqlite3"
    redis_url: str = "redis://localhost:6379/0"

    # slowapi/limits storage. "memory://" for dev/test; "redis://..." in prod.
    ratelimit_storage_uri: str = "memory://"
    ratelimit_enabled: bool = True

    # Secrets
    encryption_key: str = "dev-insecure-key-change-me-0000000000000000000"
    jwt_private_key_pem: str = ""

    # Sessions
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 60

    # Email
    email_provider: Literal["console", "smtp", "resend"] = "console"
    email_from: str = "tvtimes <no-reply@tvtimes.issinoho.com>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    resend_api_key: str = ""

    # Object storage for raw XMLTV blobs (empty -> local ./data/epg)
    s3_endpoint: str = ""
    s3_bucket: str = "tvtimes-epg"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Outbound fetch / SSRF guard
    fetch_timeout_seconds: float = 20.0
    fetch_max_bytes: int = 500 * 1024 * 1024
    fetch_allowlist: str = Field(
        default="",
        description="Comma-separated hostnames/CIDRs allowed past the private-range block.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fetch_allowlist_entries(self) -> list[str]:
        return [e.strip() for e in self.fetch_allowlist.split(",") if e.strip()]

    def assert_production_ready(self) -> None:
        """Fail fast at startup if a prod deployment is missing real secrets."""
        if self.env != "prod":
            return
        problems: list[str] = []
        if not self.jwt_private_key_pem.strip():
            problems.append("TVTIMES_JWT_PRIVATE_KEY_PEM is required in prod")
        if self.encryption_key.startswith("dev-insecure-key"):
            problems.append("TVTIMES_ENCRYPTION_KEY still holds the insecure default")
        if not self.public_origin.startswith("https://"):
            problems.append("TVTIMES_PUBLIC_ORIGIN must be https:// in prod")
        if problems:
            raise RuntimeError("insecure production config: " + "; ".join(problems))


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
