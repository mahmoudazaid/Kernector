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


def test_filter_preserves_uvicorn_access_args_for_formatter() -> None:
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/health?password=super-secret",
            "1.1",
            200,
        ),
        exc_info=None,
    )
    assert SecretRedactingFilter().filter(record) is True
    assert isinstance(record.args, tuple)
    assert len(record.args) == 5
    assert "super-secret" not in record.args[2]
    assert "[REDACTED]" in record.args[2]
    formatted = AccessFormatter(
        fmt='%(client_addr)s - "%(request_line)s" %(status_code)s'
    ).format(record)
    assert "super-secret" not in formatted
    assert "GET" in formatted
    assert "/health" in formatted


def test_filter_drops_color_message_after_clearing_args() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Uvicorn running on %s://%s:%d",
        args=("http", "127.0.0.1", 8000),
        exc_info=None,
    )
    record.__dict__["color_message"] = "Uvicorn running on %s://%s:%d"
    assert SecretRedactingFilter().filter(record) is True
    assert record.args is None
    assert "color_message" not in record.__dict__
    assert "127.0.0.1" in record.getMessage()
