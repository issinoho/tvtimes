from __future__ import annotations

import smtplib

import pytest
import respx
from app.auth import email as email_mod
from app.config import get_settings
from httpx import AsyncClient, Response


class _RecordingLog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kw: object) -> None:
        self.calls.append((event, kw))

    warning = info
    error = info


@pytest.fixture
def rec_log(monkeypatch: pytest.MonkeyPatch) -> _RecordingLog:
    log = _RecordingLog()
    monkeypatch.setattr(email_mod, "_log", log)
    return log


async def test_smtp_failure_is_swallowed_and_body_logged(
    monkeypatch: pytest.MonkeyPatch, rec_log: _RecordingLog
) -> None:
    monkeypatch.setenv("TVTIMES_EMAIL_PROVIDER", "smtp")
    get_settings.cache_clear()

    def _boom(*_a: object, **_k: object) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"Incorrect authentication data")

    monkeypatch.setattr(email_mod, "_send_smtp", _boom)

    # Must not raise.
    await email_mod.send_email(to="x@example.com", subject="hi", body_text="LINK /verify?token=abc")

    events = {e for e, _ in rec_log.calls}
    assert "email.delivery_failed" in events
    body_call = next(kw for e, kw in rec_log.calls if e == "email.undelivered_body")
    assert "token=abc" in str(body_call["body"])


@respx.mock
async def test_resend_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch, rec_log: _RecordingLog
) -> None:
    monkeypatch.setenv("TVTIMES_EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("TVTIMES_RESEND_API_KEY", "re_test")
    get_settings.cache_clear()
    respx.post("https://api.resend.com/emails").mock(return_value=Response(422))

    await email_mod.send_email(to="x@example.com", subject="hi", body_text="body")
    assert any(e == "email.delivery_failed" for e, _ in rec_log.calls)


async def test_console_provider_still_logs_and_does_not_touch_transport(
    monkeypatch: pytest.MonkeyPatch, rec_log: _RecordingLog
) -> None:
    monkeypatch.setenv("TVTIMES_EMAIL_PROVIDER", "console")
    get_settings.cache_clear()
    await email_mod.send_email(to="x@example.com", subject="hi", body_text="body")
    assert rec_log.calls == [
        ("email.console", {"to": "x@example.com", "subject": "hi", "body": "body"})
    ]


async def test_register_returns_202_when_mailer_is_broken(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a failing SMTP login used to 500 registration and roll the
    new account back."""
    monkeypatch.setenv("TVTIMES_EMAIL_PROVIDER", "smtp")
    get_settings.cache_clear()

    def _boom(*_a: object, **_k: object) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr("app.auth.email._send_smtp", _boom)

    resp = await app_client.post(
        "/api/auth/register",
        json={
            "email": "broken-mail@example.com",
            "display_name": "Sam",
            "password": "correct horse battery",
        },
    )
    assert resp.status_code == 202, resp.text

    # The account exists: a second attempt takes the "already registered" path
    # (still 202, no enumeration signal) rather than creating a duplicate.
    again = await app_client.post(
        "/api/auth/register",
        json={
            "email": "broken-mail@example.com",
            "display_name": "Sam",
            "password": "correct horse battery",
        },
    )
    assert again.status_code == 202, again.text
