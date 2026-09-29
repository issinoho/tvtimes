from __future__ import annotations

from app.logging import redact_processor


def test_redacts_secret_keyed_fields() -> None:
    out = redact_processor(None, "info", {"event": "x", "password": "hunter2long"})
    assert out["password"] == "hu***"


def test_redacts_url_userinfo_and_query_creds() -> None:
    out = redact_processor(
        None,
        "info",
        {
            "event": "fetch",
            "url": "http://user:s3cr3t@host/portal.php?mac=00:1A:79:AA:BB:CC&x=1",
        },
    )
    assert "s3cr3t" not in out["url"]
    assert "00:1A:79" not in out["url"]
    assert "x=1" in out["url"]


def test_email_bodies_keep_their_link_token() -> None:
    """#190: the console mailer's log line is the only copy of the verify link;
    masking ``?token=`` there made signup impossible without SMTP."""
    body = "Confirm:\n\nhttp://192.168.0.30:8888/verify?token=abcdef123456\n"
    for event in ("email.console", "email.undelivered_body"):
        out = redact_processor(None, "info", {"event": event, "to": "x@example.com", "body": body})
        assert out["body"] == body


def test_email_exemption_is_scoped_to_the_body_field_of_email_events() -> None:
    out = redact_processor(
        None, "info", {"event": "email.console", "url": "http://h/x?token=abcdef123456"}
    )
    assert "abcdef123456" not in out["url"]
    out = redact_processor(None, "info", {"event": "other", "body": "/verify?token=abcdef123456"})
    assert "abcdef123456" not in out["body"]
