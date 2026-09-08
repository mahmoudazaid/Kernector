"""AST helper that flags repr-equivalent interpolation in any raise message.

The scan is deliberately name-agnostic: it inspects **every** ``raise`` in a
module rather than a fixed set of exception names. A name set silently exempts
each subclass added later (``packs/software_delivery/errors.py`` defines five
``DomainValidationError`` subclasses under names no fixed set would list) and
every indirection (``raise error_type(...)`` where ``error_type`` is a
parameter). Flagging all raises designs both evasions out.

Caught mechanically — in the exception expression, its ``from`` cause, and
``Exception``-subclass ``__init__`` bodies:

- ``f"{v!r}"`` and ``f"{v!a}"`` (``!a`` is byte-identical to ``!r`` for ASCII)
- ``f"{repr(v)}"``, ``f"{sorted(x)}"``, ``f"{list(x)}"``, ``f"{tuple(x)}"``,
  ``f"{set(x)}"``, ``f"{frozenset(x)}"``, and those calls wrapped in ``str()``
  or ``format()`` (a list's ``__str__`` *is* its ``__repr__``)
- ``f"{sep.join(x)}"`` when ``join`` is ``str.join`` of a non-constant
- ``"got %r" % v`` and ``"got %s" % sorted(x)``
- ``"got " + repr(v)``
- ``"got {!r}".format(v)`` and ``"{}".format(sorted(x))``

Not flagged (safe or sanctioned):

- ``os.path.join(...)`` — that is path construction, not string join
- ``', '.join(SAFE_CONSTANT)`` where the argument is a module-level uppercase
  name (the ``*_DISPLAY`` idiom: the source is a constant, not caller input)
- a line marked ``# noqa: raise-scan``

The forms below need review; they are not dataflow-analysed here:

- Plain ``{value}``, ``str(v)``, ``"%s" % v``, and ``"{}".format(v)`` on a
  dataclass are byte-identical to ``{value!r}`` because ``object.__str__``
  falls back to ``__repr__``. Rule B (print the number) is therefore a review
  obligation: only apply it after a preceding branch has proven ``int`` /
  ``float``.
- Hoisting the message (``msg = f"...{v!r}"; raise ApplicationValidationError(msg)``)
  places the interpolation outside the ``raise`` statement and scans clean.
- Class-composed messages that interpolate caller text into
  ``super().__init__`` without a repr form above. ``!r`` / container forms
  inside ``__init__`` *are* caught; a plain ``{value}`` there is not.
"""

from __future__ import annotations

import ast
from pathlib import Path

_NOQA_MARKER = "noqa: raise-scan"
_CONTAINER_CALLS = frozenset({"repr", "sorted", "list", "tuple", "set", "frozenset"})
_WRAPPER_CALLS = frozenset({"str", "format"})
_EXCEPTION_SUFFIXES = ("Error", "Exception", "Failure")


def repr_conversions_in_raises(path: Path) -> list[int]:
    """Return line numbers where a raised exception message uses a repr form.

    Args:
        path: Python module to parse.

    Returns:
        Sorted unique line numbers of every repr-equivalent interpolation
        appearing inside a ``raise`` statement's exception or cause
        expression, or inside an exception subclass ``__init__``.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    source_lines = source.splitlines()
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            for expr in (node.exc, node.cause):
                if expr is None:
                    continue
                offenders.extend(_repr_sites_in(expr))
        elif isinstance(node, ast.ClassDef) and _is_exception_class(node):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    offenders.extend(_repr_sites_in(item))
    return sorted(
        {
            line
            for line in offenders
            if not _line_has_noqa(source_lines, line)
        }
    )


def _line_has_noqa(source_lines: list[str], lineno: int) -> bool:
    if lineno < 1 or lineno > len(source_lines):
        return False
    return _NOQA_MARKER in source_lines[lineno - 1]


def _is_exception_class(node: ast.ClassDef) -> bool:
    return any(
        _base_name(base).endswith(_EXCEPTION_SUFFIXES) for base in node.bases
    )


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _is_module_constant_name(node: ast.AST) -> bool:
    if not isinstance(node, ast.Name):
        return False
    ident = node.id.lstrip("_")
    return bool(ident) and ident.isupper()


def _is_str_join(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "join":
        return False
    receiver = func.value
    if isinstance(receiver, ast.Constant) and isinstance(receiver.value, str):
        return True
    return isinstance(receiver, ast.Name) and receiver.id == "str"


def _join_args_are_module_constants(node: ast.Call) -> bool:
    if not node.args:
        return False
    return _is_module_constant_name(node.args[0])


def _call_args(node: ast.Call) -> list[ast.AST]:
    args: list[ast.AST] = list(node.args)
    args.extend(keyword.value for keyword in node.keywords)
    return args


def _is_repr_producing_call(node: ast.AST) -> bool:
    """True when interpolating ``node`` is byte-identical to interpolating repr."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in _CONTAINER_CALLS:
        return True
    if _is_str_join(node):
        return not _join_args_are_module_constants(node)
    if isinstance(func, ast.Name) and func.id in _WRAPPER_CALLS:
        return any(_is_repr_producing_call(arg) for arg in _call_args(node))
    return False


def _rhs_renders_repr(node: ast.AST) -> bool:
    if _is_repr_producing_call(node):
        return True
    if isinstance(node, ast.Tuple):
        return any(_rhs_renders_repr(elt) for elt in node.elts)
    return False


def _repr_sites_in(node: ast.AST) -> list[int]:
    offenders: list[int] = []
    for part in ast.walk(node):
        if isinstance(part, ast.FormattedValue):
            if part.conversion in (ord("r"), ord("a")):
                offenders.append(part.lineno)
            elif _is_repr_producing_call(part.value):
                offenders.append(part.lineno)
        elif isinstance(part, ast.BinOp) and isinstance(part.op, ast.Mod):
            left = part.left
            if isinstance(left, ast.Constant) and isinstance(left.value, str):
                if "%r" in left.value:
                    offenders.append(part.lineno)
                elif "%s" in left.value and _rhs_renders_repr(part.right):
                    offenders.append(part.lineno)
        elif isinstance(part, ast.BinOp) and isinstance(part.op, ast.Add):
            if _is_repr_producing_call(part.left) or _is_repr_producing_call(
                part.right
            ):
                offenders.append(part.lineno)
        elif (
            isinstance(part, ast.Call)
            and isinstance(part.func, ast.Attribute)
            and part.func.attr == "format"
        ):
            receiver = part.func.value
            template = (
                receiver.value
                if isinstance(receiver, ast.Constant)
                and isinstance(receiver.value, str)
                else ""
            )
            if "!r" in template or "!a" in template:
                offenders.append(part.lineno)
            elif any(_is_repr_producing_call(arg) for arg in part.args):
                offenders.append(part.lineno)
    return offenders
