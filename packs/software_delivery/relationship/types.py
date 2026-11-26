"""Software Delivery relation types and inverse display names (ADR 0011)."""

from __future__ import annotations

from collections.abc import Mapping

# Canonical relation token -> inverse display name when listing from the object.
RELATION_INVERSE_NAMES: Mapping[str, str] = {
    "tests": "tested_by",
    "blocks": "blocked_by",
    "child_of": "parent_of",
    "relates_to": "relates_to",
    "affects": "affected_by",
}
