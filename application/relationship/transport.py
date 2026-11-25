"""Strip namespaced relationship transport keys from ingest metadata (#374)."""

from __future__ import annotations

from collections.abc import Mapping

TRANSPORT_KEY_PREFIX = "kernector."


def strip_transport_extra(extra: Mapping[str, str]) -> dict[str, str]:
    """Return ``extra`` without ``kernector.*`` transport keys."""
    return {
        key: value
        for key, value in extra.items()
        if not key.startswith(TRANSPORT_KEY_PREFIX)
    }
