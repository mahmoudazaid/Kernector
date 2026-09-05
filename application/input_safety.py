"""Deterministic query-input reject rules at application boundaries.

Pattern rejection is defense-in-depth, not complete prompt-injection
protection. Structural trust tiers in ``grounded_rag_policy`` remain the
primary bound: retrieved text stays out of the system role, and optional
task prompts never displace platform policy. A matcher can miss novel
phrasing; callers must not treat a pass as proof the input is safe.

The reject message is a fixed constant. It must never echo the matched
pattern or any span of user text — presentation adapters surface
``str(error)`` directly, and naming what fired would give an attacker an
oracle for probing the list.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from application.errors import InputRejectedError
from application.grounded_rag_policy import CONTEXT_CLOSE, CONTEXT_OPEN

UNSAFE_QUERY_MESSAGE = (
    "This query cannot be processed. Rephrase without instruction overrides "
    "or attempts to alter system behaviour."
)

# Imperative-anchored platform patterns. Match at the start of the text or
# after a sentence boundary so questions *about* jailbreak phrases still pass.
_PLATFORM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:^|[\n.!?])\s*ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        re.I,
    ),
    re.compile(
        r"(?:^|[\n.!?])\s*disregard\s+(all\s+)?(previous|prior|above)\s+instructions",
        re.I,
    ),
    re.compile(
        r"(?:^|[\n.!?])\s*reveal\s+(your\s+)?(system\s+)?prompt",
        re.I,
    ),
    re.compile(re.escape(CONTEXT_OPEN), re.I),
    re.compile(re.escape(CONTEXT_CLOSE), re.I),
)


def reject_unsafe_query(
    text: str,
    *,
    extra_patterns: Sequence[str] = (),
) -> None:
    """Raise when ``text`` matches a platform or pack reject pattern.

    Args:
        text: Caller-supplied query or history message content.
        extra_patterns: Optional pack-configured literal substrings
            (case-insensitive). Empty for General mode / retrieve-only.

    Raises:
        InputRejectedError: A platform or extra pattern matched.
            The message is ``UNSAFE_QUERY_MESSAGE`` and never includes
            ``text`` or the matched pattern.
    """
    candidates: list[re.Pattern[str]] = list(_PLATFORM_PATTERNS)
    for pattern in extra_patterns:
        if pattern:
            candidates.append(re.compile(re.escape(pattern), re.I))
    for compiled in candidates:
        if compiled.search(text):
            raise InputRejectedError(UNSAFE_QUERY_MESSAGE)
