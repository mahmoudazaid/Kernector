"""Configure stdlib logging for the process from LOG_LEVEL."""

from __future__ import annotations

import logging
import os

_FORMAT = "%(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    """Apply ``LOG_LEVEL`` (default ``INFO``) to the root logger.

    Idempotent enough for app bootstrap: sets the root level every call. Adds a
    basic handler only when the root logger has none yet, so test runners and
    hosts that already configured logging keep their handlers.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=_FORMAT)
    else:
        root.setLevel(level)
