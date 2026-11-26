"""Strip namespaced relationship transport keys from ingest metadata (#374)."""

from __future__ import annotations

from collections.abc import Mapping

TRANSPORT_KEY_PREFIX = "kernector."
# Neutral listing/sync fingerprint shared by every provider (not Jira-specific).
LINKS_FINGERPRINT_EXTRA_KEY = "kernector.links_fingerprint.v1"


def strip_transport_extra(extra: Mapping[str, str]) -> dict[str, str]:
    """Return ``extra`` without ``kernector.*`` transport keys."""
    return {
        key: value
        for key, value in extra.items()
        if not key.startswith(TRANSPORT_KEY_PREFIX)
    }
