"""AST helpers that flag unsafe ``!r`` interpolation in validation raises.

A green scan is not a full proof of safe messages:

- Plain ``{value}`` on a dataclass is byte-identical to ``{value!r}`` because
  ``object.__str__`` falls back to ``__repr__``. Detecting that statically
  requires proving the target is numeric in the enclosing branch — not done
  here. Rule B (print the number) is therefore a review obligation: only
  apply it after a preceding branch has proven ``int`` / ``float``.
- Hoisting the message (``msg = f"...{v!r}"; raise ApplicationValidationError(msg)``)
  places the ``!r`` outside ``raise``'s exception expression and scans clean.
  No production site does this today; catch it in review.

Extend :data:`VALIDATION_ERRORS` when a new validation exception type is added
(see the error-taxonomy table in ``ARCHITECTURE.md``).
"""

from __future__ import annotations

import ast
from pathlib import Path

# Names of exception types whose raise messages must not embed ``!r``.
# Keep in sync with the error-taxonomy table in ARCHITECTURE.md.
VALIDATION_ERRORS = {
    "DomainValidationError",
    "ApplicationValidationError",
    "ToolArgumentValidationError",
    "InputRejectedError",
    "UnknownPromptError",
    "UnknownDocumentError",
}


def repr_conversions_in_validation_raises(path: Path) -> list[int]:
    """Return line numbers where a validation raise interpolates with ``!r``.

    Only ``raise <ValidationError>(...)`` call forms are scanned. Subclasses
    whose names are absent from :data:`VALIDATION_ERRORS` are invisible.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in VALIDATION_ERRORS:
            continue
        for part in ast.walk(node.exc):
            if isinstance(part, ast.FormattedValue) and part.conversion == ord("r"):
                offenders.append(part.lineno)
    return offenders
