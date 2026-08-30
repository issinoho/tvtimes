"""Credential masking for logs and API responses (ported from
``tvdinner.redact`` plus the xtream/stalker scheme-specific redactors)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_XTREAM_PATH_CREDS_RE = re.compile(r"(/(?:live|movie|series)/[^/]+/)([^/]+)(/)")
_QUERY_CRED_RE = re.compile(
    r"(?:^|[?&])(password|token|api_key|apikey|X-Plex-Token|mac)=([^&]+)", re.IGNORECASE
)
_USERINFO_RE = re.compile(r"://([^/:@\s]+):([^/@\s]+)@")


def redact_resource_url(url: str) -> str:
    """Best-effort mask of credentials embedded in a resource URL."""

    def _mask_path(m: re.Match[str]) -> str:
        pw = m.group(2)
        return f"{m.group(1)}{pw[:2] + '***' if len(pw) > 2 else '***'}{m.group(3)}"

    url = _XTREAM_PATH_CREDS_RE.sub(_mask_path, url, count=1)
    url = _USERINFO_RE.sub(lambda m: f"://{m.group(1)}:***@", url)

    def _mask_query(m: re.Match[str]) -> str:
        val = m.group(2)
        return m.group(0).replace(val, f"{val[:4]}***" if len(val) > 4 else "***")

    return _QUERY_CRED_RE.sub(_mask_query, url)


def redact_mac(mac: str) -> str:
    parts = mac.split(":")
    if len(parts) <= 2:
        return "**"
    return ":".join(parts[:2] + ["**"] * (len(parts) - 2))


def source_config_summary(kind: str, config: dict[str, object]) -> str:
    """A short, credential-free description of a source's config for the API."""
    if kind == "m3u":
        url = str(config.get("url", ""))
        p = urlsplit(url)
        return f"{p.scheme}://{p.hostname}{p.path}" if p.hostname else redact_resource_url(url)
    if kind == "xtream":
        p = urlsplit(str(config.get("server_url", "")))
        user = str(config.get("username", ""))
        return f"{user[:2]}***@{p.hostname}{':' + str(p.port) if p.port else ''}"
    if kind == "stalker":
        p = urlsplit(str(config.get("portal_url", "")))
        return f"{p.hostname}{p.path} · {redact_mac(str(config.get('mac', '')))}"
    if kind == "hdhomerun":
        url = str(config.get("device_url", "")).strip()
        return url or "auto-discover on LAN"
    return "unknown source"
