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
