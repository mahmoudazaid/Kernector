"""AST helper that flags repr-equivalent interpolation in any raise message.

The scan is deliberately name-agnostic: it inspects **every** ``raise`` in a
module rather than a fixed set of exception names. A name set silently exempts
each subclass added later (``packs/software_delivery/errors.py`` defines five
``DomainValidationError`` subclasses under names no fixed set would list) and
every indirection (``raise error_type(...)`` where ``error_type`` is a
parameter). Flagging all raises designs both evasions out.

Caught mechanically — in the exception expression **and** its ``from`` cause:

- ``f"{v!r}"``
- ``f"{repr(v)}"``, ``f"{sorted(x)}"``, ``f"{list(x)}"``, ``f"{tuple(x)}"``,
  ``f"{set(x)}"``, ``f"{frozenset(x)}"``, and ``f"{sep.join(x)}"`` (a list's
  ``__str__`` *is* its ``__repr__``, so container interpolation is byte-identical
  to ``!r``)
- ``"got %r" % v``
- ``"got " + repr(v)``
- ``"got {!r}".format(v)``

The forms below need review; they are not dataflow-analysed here:

- Plain ``{value}`` on a dataclass is byte-identical to ``{value!r}`` because
  ``object.__str__`` falls back to ``__repr__``. Rule B (print the number) is
  therefore a review obligation: only apply it after a preceding branch has
  proven ``int`` / ``float``.
- Hoisting the message (``msg = f"...{v!r}"; raise ApplicationValidationError(msg)``)
  places the interpolation outside the ``raise`` statement and scans clean.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPR_CALLS = frozenset({"repr", "sorted", "list", "tuple", "set", "frozenset"})


def repr_conversions_in_raises(path: Path) -> list[int]:
    """Return line numbers where a raised exception message uses a repr form.

    Args:
        path: Python module to parse.

    Returns:
        Sorted unique line numbers of every repr-equivalent interpolation
        appearing inside a ``raise`` statement's exception or cause expression.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        for expr in (node.exc, node.cause):
            if expr is None:
                continue
            offenders.extend(_repr_sites_in(expr))
    return sorted(set(offenders))


def _is_container_or_repr_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in _REPR_CALLS:
        return True
    return isinstance(func, ast.Attribute) and func.attr == "join"


def _repr_sites_in(node: ast.AST) -> list[int]:
    offenders: list[int] = []
    for part in ast.walk(node):
        if isinstance(part, ast.FormattedValue):
            if part.conversion == ord("r"):
                offenders.append(part.lineno)
            elif _is_container_or_repr_call(part.value):
                offenders.append(part.lineno)
        elif isinstance(part, ast.BinOp) and isinstance(part.op, ast.Mod):
            left = part.left
            if (
                isinstance(left, ast.Constant)
                and isinstance(left.value, str)
                and "%r" in left.value
            ):
                offenders.append(part.lineno)
        elif isinstance(part, ast.BinOp) and isinstance(part.op, ast.Add):
            if _is_container_or_repr_call(part.left) or _is_container_or_repr_call(
                part.right
            ):
                offenders.append(part.lineno)
        elif (
            isinstance(part, ast.Call)
            and isinstance(part.func, ast.Attribute)
            and part.func.attr == "format"
        ):
            receiver = part.func.value
            if (
                isinstance(receiver, ast.Constant)
                and isinstance(receiver.value, str)
                and "!r" in receiver.value
            ):
                offenders.append(part.lineno)
    return offenders
