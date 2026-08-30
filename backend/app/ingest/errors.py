"""Ingestion errors. ``message`` is safe to show the user (already redacted)."""

from __future__ import annotations


class SourceError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SourceRejected(SourceError):
    """The URL is not allowed (private/loopback address, bad scheme, too big)."""


class SourceUnreachable(SourceError):
    """Network failure, timeout, or an HTTP error from the source."""


class SourceInvalid(SourceError):
    """Reached the source but the response wasn't the expected format /
    credentials were refused."""
