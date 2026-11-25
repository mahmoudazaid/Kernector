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
    """Redact secrets in log messages, args, and exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact_secrets(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact_secrets(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        if record.exc_info and not record.exc_text:
            record.exc_text = redact_secrets(
                logging.Formatter().formatException(record.exc_info)
            )
        elif isinstance(record.exc_text, str):
            record.exc_text = redact_secrets(record.exc_text)
        return True


def install_secret_redacting_filter(logger: logging.Logger | None = None) -> None:
    """Attach :class:`SecretRedactingFilter` to *logger* and its handlers."""
    target = logger if logger is not None else logging.getLogger()
    filt = SecretRedactingFilter()
    if not any(isinstance(existing, SecretRedactingFilter) for existing in target.filters):
        target.addFilter(filt)
    for handler in list(target.handlers):
        if not any(
            isinstance(existing, SecretRedactingFilter) for existing in handler.filters
        ):
            handler.addFilter(filt)
    # Also cover root handlers used by uvicorn / basicConfig.
    root = logging.getLogger()
    if target is not root:
        if not any(
            isinstance(existing, SecretRedactingFilter) for existing in root.filters
        ):
            root.addFilter(filt)
        for handler in list(root.handlers):
            if not any(
                isinstance(existing, SecretRedactingFilter)
                for existing in handler.filters
            ):
                handler.addFilter(filt)
