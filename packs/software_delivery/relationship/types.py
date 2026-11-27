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
    "automates": "automated_by",
    "references": "referenced_by",
    "describes": "described_by",
    "exercises": "exercised_by",
}

# Subject context -> relation type for API-mention edges (#375).
CONTEXT_RELATIONS: Mapping[str, str] = {
    "business": "references",
    "frontend": "references",
    "backend": "references",
    "operations": "references",
    "testing": "exercises",
    "documentation": "describes",
}
