"""Application settings, loaded from environment (prefix ``TVTIMES_``)."""

from __future__ import annotations

import base64
import functools
import sys
from typing import Literal
from urllib.parse import urlsplit

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
    # Optional second public origin for players outside the LAN (e.g.
    # https://stream.example.com, its own reverse-proxy host). Export, stream,
    # relay and pairing URLs answer with the origin the request arrived on:
    # this one when the Host header is its host, else public_origin. Only these
    # two configured values can ever be written into a URL.
    stream_origin: str = ""

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

    # Stream relay (services/relay.py). A source with ``relay_streams`` set has
    # its export /stream URL proxied through tvtimes instead of 302'd to the
    # upstream, so a LAN-only tuner plays from anywhere and provider credentials
    # never reach the client. ``relay_enabled=False`` turns every source back
    # into a 302. The caps are per process (the registry is in memory).
    relay_enabled: bool = True
    # A viewer on the LAN gets the 302 even for a relayed source: the direct
    # path is the cheaper one there. Needs ``trusted_proxies`` set when a
    # reverse proxy sits in front, or proxied viewers are always relayed.
    relay_lan_direct: bool = True
    relay_max_streams_per_tenant: int = 4
    relay_max_streams_total: int = 16
    relay_connect_timeout_seconds: float = 10.0
    # Idle read timeout: how long a relayed upstream may send nothing at all.
    relay_read_timeout_seconds: float = 30.0
    # Lifetimes of the opaque tokens in a rewritten HLS playlist: segments and
    # keys are short, nested playlists (and everything in a VOD playlist) long.
    relay_segment_ttl_seconds: int = 600
    relay_playlist_ttl_seconds: int = 43200
    relay_manifest_max_bytes: int = 2 * 1024 * 1024
    # HLS fetches a segment every few seconds per viewer; the default 240/min
    # would throttle a household sharing one public IP.
    relay_segment_rate_limit: str = "900/minute"
    # Empty -> the same tvtimes/<version> User-Agent as every other fetch.
    relay_user_agent: str = ""

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

    @field_validator("stream_origin", mode="after")
    @classmethod
    def _check_stream_origin(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value:
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
                raise ValueError(
                    "TVTIMES_STREAM_ORIGIN must be a bare origin like https://stream.example.com"
                )
        return value

    def origin_for(self, host: str | None) -> str:
        """The origin to write into URLs for a request whose Host header is
        ``host``: ``stream_origin`` if that is the host it came in on, else
        ``public_origin``. Never the Host header itself."""
        if (
            self.stream_origin
            and host
            and host.strip().lower() == urlsplit(self.stream_origin).netloc.lower()
        ):
            return self.stream_origin
        return self.public_origin.rstrip("/")

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
