"""Auth secret redaction (#182)."""

from __future__ import annotations

import logging

from presentation.http.redaction import (
    SecretRedactingFilter,
    install_secret_redacting_filter,
    redact_secrets,
)


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


def test_redact_secrets_masks_json_password_bodies() -> None:
    raw = '{"password": "hunter2", "csrf_token": "abc"}'
    redacted = redact_secrets(raw)
    assert "hunter2" not in redacted
    assert "abc" not in redacted
    assert "[REDACTED]" in redacted


def test_filter_redacts_rendered_message_and_args() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="failed: %s",
        args=(KeyError("password=super-secret"),),
        exc_info=None,
    )
    assert SecretRedactingFilter().filter(record) is True
    assert "super-secret" not in record.getMessage()
    assert record.args is None


def test_filter_redacts_percent_format_without_breaking_logging() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="password=%s rejected for %s",
        args=("hunter2", "alice"),
        exc_info=None,
    )
    assert SecretRedactingFilter().filter(record) is True
    rendered = record.getMessage()
    assert "hunter2" not in rendered
    assert "[REDACTED]" in rendered
    assert "alice" in rendered


def test_install_attaches_to_uvicorn_loggers() -> None:
    install_secret_redacting_filter()
    uvicorn_error = logging.getLogger("uvicorn.error")
    assert any(
        isinstance(item, SecretRedactingFilter) for item in uvicorn_error.filters
    )
