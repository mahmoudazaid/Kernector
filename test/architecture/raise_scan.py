"""AST helper that flags ``!r`` interpolation in any raise message.

The scan is deliberately name-agnostic: it inspects **every** ``raise`` in a
module rather than a fixed set of exception names. A name set silently exempts
each subclass added later (``packs/software_delivery/errors.py`` defines five
``DomainValidationError`` subclasses under names no fixed set would list) and
every indirection (``raise error_type(...)`` where ``error_type`` is a
parameter). Flagging all raises designs both evasions out.

A green scan is still not a full proof of safe messages:

- Plain ``{value}`` on a dataclass is byte-identical to ``{value!r}`` because
  ``object.__str__`` falls back to ``__repr__``. Detecting that statically
  requires proving the target is numeric in the enclosing branch — not done
  here. Rule B (print the number) is therefore a review obligation: only
  apply it after a preceding branch has proven ``int`` / ``float``.
- Hoisting the message (``msg = f"...{v!r}"; raise ApplicationValidationError(msg)``)
  places the ``!r`` outside the ``raise`` statement and scans clean. No
  production site does this today; catch it in review.
"""

from __future__ import annotations

import ast
from pathlib import Path


def repr_conversions_in_raises(path: Path) -> list[int]:
    """Return line numbers where a raised exception message uses ``!r``.

    Args:
        path: Python module to parse.

    Returns:
        Sorted line numbers of every ``!r`` conversion appearing inside a
        ``raise`` statement's exception expression.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        for part in ast.walk(node.exc):
            if isinstance(part, ast.FormattedValue) and part.conversion == ord("r"):
                offenders.append(part.lineno)
    return sorted(offenders)
