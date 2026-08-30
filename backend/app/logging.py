"""Structured logging setup.

A redaction processor masks anything that looks like a credential before it
reaches a sink. Phase 3 will route source-specific redactors
(``app.ingest.redact``) through here too.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog

_SECRET_KEY_RE = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|mac)",
    re.IGNORECASE,
)
_QUERY_CRED_RE = re.compile(
    r"([?&](?:password|token|api_key|apikey|mac)=)([^&\s]+)",
    re.IGNORECASE,
)
_USERINFO_RE = re.compile(r"://([^/:@\s]+):([^/@\s]+)@")


def _mask(value: str) -> str:
    return value[:2] + "***" if len(value) > 4 else "***"


def redact_processor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, val in list(event_dict.items()):
        if isinstance(val, str):
            val = _QUERY_CRED_RE.sub(lambda m: m.group(1) + "***", val)
            val = _USERINFO_RE.sub(lambda m: f"://{m.group(1)}:***@", val)
            event_dict[key] = val
        if _SECRET_KEY_RE.search(key) and isinstance(event_dict[key], str):
            event_dict[key] = _mask(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", *, json: bool = False) -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
