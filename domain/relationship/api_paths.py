"""Normalize API method/path identities for deterministic matching (#375)."""

from __future__ import annotations

import re

_PARAM = re.compile(r"\{[^}/]+\}|\$\{[^}/]+\}|:[A-Za-z_][A-Za-z0-9_]*")


def normalize_api_path(path: str) -> str:
    """Normalize path-template placeholders to a single ``{}`` token."""
    cleaned = path.strip().strip("`\"'")
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned.lstrip("/")
    return _PARAM.sub("{}", cleaned)


def normalize_method_path(method: str, path: str) -> str:
    return f"{method.upper()} {normalize_api_path(path)}"
