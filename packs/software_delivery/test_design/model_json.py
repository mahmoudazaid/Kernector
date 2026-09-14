"""Strict JSON extraction for test-design model outputs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from domain.errors import ToolFailureError

_FENCE = re.compile(
    r"^```(?:json)?\s*\n?(?P<body>.*?)\n?```\s*$",
    re.IGNORECASE | re.DOTALL,
)


def loads_model_json_object(content: str, *, failure_prefix: str) -> Mapping[str, object]:
    """Parse a model reply into a JSON object.

    Accepts raw JSON or a single fenced `` ```json `` block. Does not repair
    truncated payloads — those remain ``ToolFailureError``.

    Args:
        content: Model reply text.
        failure_prefix: Sanitized message prefix for parse failures.

    Returns:
        Mapping[str, object]: Parsed JSON object.

    Raises:
        ToolFailureError: Empty, non-object, or invalid JSON.
    """
    if not isinstance(content, str) or not content.strip():
        raise ToolFailureError(f"{failure_prefix} was empty")
    text = content.strip()
    fence = _FENCE.match(text)
    if fence is not None:
        text = fence.group("body").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ToolFailureError(f"{failure_prefix} was not valid JSON") from error
    if not isinstance(data, Mapping):
        raise ToolFailureError(f"{failure_prefix} must be a JSON object")
    return data
