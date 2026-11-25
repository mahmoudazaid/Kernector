"""Redact auth secrets from log and error text (#182)."""

from __future__ import annotations

import logging
import re

# JSON ("password": "…") and key=value / key: value forms.
_PASSWORD_KEYS = re.compile(
    r'(?i)(["\']?(?:password|passwd|pwd)["\']?\s*[:=]\s*)'
    r'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|([^\s,;]+))'
)
_COOKIE_SESSION = re.compile(
    r"(?i)(kernector_session)=([^;\s]+)"
)
_CSRF_HEADER = re.compile(
    r'(?i)(["\']?(?:x-csrf-token|csrf_token)["\']?\s*[:=]\s*)'
    r'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|([^\s,;]+))'
)

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact_secrets(text: str) -> str:
    """Return *text* with passwords, session cookies, and CSRF tokens masked."""

    def _sub_quoted(match: re.Match[str]) -> str:
        prefix = match.group(1)
        if match.group(2) is not None:
            return f'{prefix}"[REDACTED]"'
        if match.group(3) is not None:
            return f"{prefix}'[REDACTED]'"
        return f"{prefix}[REDACTED]"

    out = _PASSWORD_KEYS.sub(_sub_quoted, text)
    out = _COOKIE_SESSION.sub(r"\1=[REDACTED]", out)
    out = _CSRF_HEADER.sub(_sub_quoted, out)
    return out


class SecretRedactingFilter(logging.Filter):
    """Redact secrets in the rendered log message and exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        # AccessFormatter unpacks record.args — redact in place, do not clear.
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            record.args = tuple(
                redact_secrets(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
            return True

        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact_secrets(rendered)
        record.args = None
        # ColourizedFormatter would re-format color_message with the old args.
        record.__dict__.pop("color_message", None)
        if record.exc_info and not record.exc_text:
            record.exc_text = redact_secrets(
                logging.Formatter().formatException(record.exc_info)
            )
        elif isinstance(record.exc_text, str):
            record.exc_text = redact_secrets(record.exc_text)
        return True


def _attach_filter(logger: logging.Logger, filt: SecretRedactingFilter) -> None:
    if not any(isinstance(existing, SecretRedactingFilter) for existing in logger.filters):
        logger.addFilter(filt)
    for handler in list(logger.handlers):
        if not any(
            isinstance(existing, SecretRedactingFilter) for existing in handler.filters
        ):
            handler.addFilter(filt)


def install_secret_redacting_filter(logger: logging.Logger | None = None) -> None:
    """Attach :class:`SecretRedactingFilter` to *logger*, root, and uvicorn."""
    filt = SecretRedactingFilter()
    target = logger if logger is not None else logging.getLogger()
    _attach_filter(target, filt)
    root = logging.getLogger()
    if target is not root:
        _attach_filter(root, filt)
    for name in _UVICORN_LOGGERS:
        _attach_filter(logging.getLogger(name), filt)
