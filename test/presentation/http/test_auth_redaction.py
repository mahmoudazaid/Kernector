"""Auth secret redaction (#182)."""

from __future__ import annotations

from presentation.http.redaction import redact_secrets


def test_redact_secrets_masks_password_cookie_and_csrf() -> None:
    raw = (
        "password=super-secret "
        "kernector_session=session-plaintext-value "
        "X-CSRF-Token: csrf-plaintext-value "
        'csrf_token: "csrf-json-value"'
    )
    redacted = redact_secrets(raw)
    assert "super-secret" not in redacted
    assert "session-plaintext-value" not in redacted
    assert "csrf-plaintext-value" not in redacted
    assert "csrf-json-value" not in redacted
    assert "[REDACTED]" in redacted
