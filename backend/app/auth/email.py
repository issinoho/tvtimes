"""Transactional email for verification and password-reset links.

Providers: ``console`` (dev — logs the link), ``smtp`` (stdlib, run off-thread),
``resend`` (HTTPS API). The caller builds the link; this module only delivers.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import anyio
import httpx

from app.config import get_settings
from app.logging import get_logger

_log = get_logger("auth.email")


async def send_email(*, to: str, subject: str, body_text: str) -> None:
    """Deliver a transactional email. Fail-open: a provider error is logged
    (along with the message body, so the link is recoverable) but not raised —
    a broken mailer must not 500 registration or password reset, nor become an
    account-enumeration oracle."""
    provider = get_settings().email_provider
    if provider == "console":
        _log.info("email.console", to=to, subject=subject, body=body_text)
        return
    try:
        if provider == "smtp":
            await anyio.to_thread.run_sync(_send_smtp, to, subject, body_text)
        elif provider == "resend":
            await _send_resend(to, subject, body_text)
        else:
            raise RuntimeError(f"unknown email provider {provider!r}")
    except Exception as exc:
        _log.error(
            "email.delivery_failed",
            provider=provider,
            to=to,
            subject=subject,
            error=f"{type(exc).__name__}: {exc}",
        )
        # Surface the content so an operator can complete the flow by hand.
        _log.warning("email.undelivered_body", to=to, subject=subject, body=body_text)


def _build_message(to: str, subject: str, body_text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = get_settings().email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_text)
    return msg


def _send_smtp(to: str, subject: str, body_text: str) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as server:
        server.starttls()
        if s.smtp_username:
            server.login(s.smtp_username, s.smtp_password)
        server.send_message(_build_message(to, subject, body_text))


async def _send_resend(to: str, subject: str, body_text: str) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            json={"from": s.email_from, "to": [to], "subject": subject, "text": body_text},
        )
        resp.raise_for_status()
