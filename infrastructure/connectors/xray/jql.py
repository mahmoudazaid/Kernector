"""JQL helpers shared by the Xray Server and Cloud adapters (#400)."""

from __future__ import annotations


def jql_string(value: str) -> str:
    """Quote ``value`` as a JQL string literal, escaping ``\\`` and ``"``."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
