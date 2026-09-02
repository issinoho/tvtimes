"""Application settings, loaded from environment (prefix ``TVTIMES_``)."""

from __future__ import annotations

import base64
import functools
import sys
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "prod"]


def _is_fernet_key(value: str) -> bool:
    """True only for a real ``Fernet.generate_key()`` value — urlsafe-base64
    decoding to exactly 32 bytes. Anything else is passphrase-derived and
    brute-forceable (see ``app.auth.crypto._derive_key``)."""
    try:
        return len(base64.urlsafe_b64decode(value.encode("utf-8"))) == 32
    except (ValueError, TypeError):
        return False


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

    # Directory holding the built SPA (index.html + assets). When set and
    # present, the API also serves the web app at ``/`` (same origin, so no
    # CORS and a first-party refresh cookie). The all-in-one Docker image sets
    # this; a split deployment leaves it empty.
    static_dir: str = ""

    # slowapi/limits storage. "memory://" for dev/test; "redis://..." in prod.
    ratelimit_storage_uri: str = "memory://"
    ratelimit_enabled: bool = True

    # Comma-separated proxy IPs / CIDRs whose ``X-Forwarded-For`` we trust.
    # Empty (the default) means tvtimes is reached directly, so XFF is ignored
    # entirely and a client can't spoof its address to dodge rate limits or
    # poison the audit log. Set this to your reverse proxy's address *as the
    # container sees it* when you run one (e.g. 172.16.0.0/12 for the Docker
    # bridge, or 127.0.0.1 for a same-host proxy).
    trusted_proxies: str = ""

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

    # Outbound fetch / SSRF guard. fetch_max_bytes caps both the downloaded
    # body and, for a gzip response, its decompressed size — so it also bounds
    # a decompression bomb. 256 MiB is well above the largest real XMLTV feeds.
    fetch_timeout_seconds: float = 20.0
    fetch_max_bytes: int = 256 * 1024 * 1024
    fetch_allowlist: str = Field(
        default="",
        description="Comma-separated hostnames/CIDRs allowed past the private-range block.",
    )

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        """Accept the URLs hosting providers hand out. ``postgres://`` (Heroku
        et al.) and a driver-less ``postgresql://`` both need the async driver
        this app uses."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fetch_allowlist_entries(self) -> list[str]:
        return [e.strip() for e in self.fetch_allowlist.split(",") if e.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trusted_proxy_entries(self) -> list[str]:
        return [e.strip() for e in self.trusted_proxies.split(",") if e.strip()]

    def assert_production_ready(self) -> None:
        """At startup: hard-fail if real secrets are missing; warn about a
        weaker-than-ideal setup (e.g. plain HTTP) without blocking self-hosters
        who terminate TLS at their own reverse proxy."""
        if self.env != "prod":
            return
        problems: list[str] = []
        if not self.jwt_private_key_pem.strip():
            problems.append("TVTIMES_JWT_PRIVATE_KEY_PEM is required in prod")
        if self.encryption_key.startswith("dev-insecure-key"):
            problems.append("TVTIMES_ENCRYPTION_KEY still holds the insecure default")
        elif not _is_fernet_key(self.encryption_key):
            problems.append(
                "TVTIMES_ENCRYPTION_KEY must be a generated 32-byte urlsafe-base64 key "
                '(python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"), not a passphrase'
            )
        if problems:
            raise RuntimeError("insecure production config: " + "; ".join(problems))
        if not self.public_origin.startswith("https://"):
            print(
                "tvtimes: WARNING — TVTIMES_PUBLIC_ORIGIN is not https://. Passkeys "
                "and Secure cookies need HTTPS; run tvtimes behind a TLS-terminating "
                "reverse proxy for anything beyond a trusted LAN.",
                file=sys.stderr,
            )


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
