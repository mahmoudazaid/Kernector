"""Shared assertions for provider error sanitization (#462)."""

from __future__ import annotations

import logging
from collections.abc import Iterable


def assert_no_secret_leakage(
    exc: BaseException,
    *,
    secret: str = "sk-secret",
    logger: logging.Logger | None = None,
) -> None:
    """Assert ``exc`` does not expose ``secret`` on public surfaces."""
    assert secret not in str(exc)
    assert secret not in repr(exc)
    assert exc.__cause__ is None or secret not in str(exc.__cause__)
    assert exc.__cause__ is None or secret not in repr(exc.__cause__)

    if logger is not None:
        try:
            logger.exception("provider_failure", exc_info=exc)
        except Exception:
            pass
        # Best-effort: formatted exception text must not include the secret.
        formatted = logging.Formatter().formatException(
            (type(exc), exc, exc.__traceback__)
        )
        assert secret not in formatted


def assert_cause_is_safe(exc: BaseException, *, forbidden: Iterable[str]) -> None:
    """Assert ``__cause__`` is absent or contains none of ``forbidden``."""
    cause = exc.__cause__
    if cause is None:
        return
    text = f"{cause!s}\n{cause!r}"
    for token in forbidden:
        assert token not in text
