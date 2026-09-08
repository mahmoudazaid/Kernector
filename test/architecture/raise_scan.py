"""AST helper that flags repr-equivalent interpolation in any raise message.

The scan is deliberately name-agnostic: it inspects **every** ``raise`` in a
module rather than a fixed set of exception names. A name set silently exempts
each subclass added later (``packs/software_delivery/errors.py`` defines five
``DomainValidationError`` subclasses under names no fixed set would list) and
every indirection (``raise error_type(...)`` where ``error_type`` is a
parameter). Flagging all raises designs both evasions out.

Caught mechanically — in the exception expression, its ``from`` cause, and
every method body of every ``ClassDef``:

- ``f"{v!r}"`` and ``f"{v!a}"`` (``!a`` is byte-identical to ``!r`` for ASCII)
- ``f"{repr(v)}"``, ``f"{sorted(x)}"``, ``f"{list(x)}"``, ``f"{tuple(x)}"``,
  ``f"{set(x)}"``, ``f"{frozenset(x)}"``, ``f"{dict(x)}"``, and those calls
  wrapped in ``str()`` or ``format()`` (a list's ``__str__`` *is* its
  ``__repr__``)
- ``f"{unknown.keys()}"``, ``f"{unknown.values()}"``, ``f"{unknown[:3]}"``
- ``f"{sep.join(x)}"`` when ``join`` is not ``os.path.join`` / friends and
  the argument is not a module-level constant binding
- ``"got %r" % v`` and ``"got %s" % sorted(x)``
- ``"got " + repr(v)``
- ``"got {!r}".format(v)`` and ``"{}".format(sorted(x))``

Not flagged (safe or sanctioned):

- ``os.path.join(...)`` — that is path construction, not string join
- ``', '.join(SAFE_CONSTANT)`` where the argument is a top-level constant
  binding to a literal (the ``*_DISPLAY`` idiom: the source is a constant,
  not caller input)
- a line marked ``# noqa: raise-scan``

The forms below need review; they are not dataflow-analysed here:

- Plain ``{value}``, ``str(v)``, ``"%s" % v``, and ``"{}".format(v)`` on a
  dataclass are byte-identical to ``{value!r}`` because ``object.__str__``
  falls back to ``__repr__``. Rule B (print the number) is therefore a review
  obligation: only apply it after a preceding branch has proven ``int`` /
  ``float``.
- Hoisting the message (``msg = f"...{v!r}"; raise ApplicationValidationError(msg)``)
  places the interpolation outside the ``raise`` statement and scans clean.
- Class-composed messages that interpolate caller text without a
  repr-equivalent form above. A plain ``{value}`` there is not flagged.
"""

from __future__ import annotations

import ast
from pathlib import Path

_NOQA_MARKER = "noqa: raise-scan"
_CONTAINER_CALLS = frozenset(
    {"repr", "sorted", "list", "tuple", "set", "frozenset", "dict"}
)
_WRAPPER_CALLS = frozenset({"str", "format"})
_SAFE_JOIN_RECEIVERS = frozenset({"path", "posixpath", "ntpath"})
_VIEW_METHODS = frozenset({"keys", "values", "items"})


def repr_conversions_in_raises(path: Path) -> list[int]:
    """Return line numbers where a raised exception message uses a repr form.

    Args:
        path: Python module to parse.

    Returns:
        Sorted unique line numbers of every repr-equivalent interpolation
        appearing inside a ``raise`` statement's exception or cause
        expression, or inside any method of any class.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    source_lines = source.splitlines()
    constants = _module_constants(tree)
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            for expr in (node.exc, node.cause):
                if expr is None:
                    continue
                offenders.extend(_repr_sites_in(expr, constants))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    offenders.extend(_repr_sites_in(item, constants))
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


def _is_constant_expr(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_constant_expr(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            _is_constant_expr(key) and _is_constant_expr(value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
        )
    if isinstance(node, ast.UnaryOp) and isinstance(
        node.op, (ast.UAdd, ast.USub, ast.Not)
    ):
        return _is_constant_expr(node.operand)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {"frozenset", "tuple", "list", "set", "dict"}:
            return all(_is_constant_expr(arg) for arg in node.args) and all(
                _is_constant_expr(kw.value) for kw in node.keywords
            )
    return False


def _module_constants(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not _is_constant_expr(node.value):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and _is_constant_expr(node.value):
                names.add(node.target.id)
    return frozenset(names)


def _is_str_join(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "join":
        return False
    receiver = func.value
    if isinstance(receiver, ast.Attribute) and receiver.attr in _SAFE_JOIN_RECEIVERS:
        return False
    return True


def _join_args_are_module_constants(
    node: ast.Call, constants: frozenset[str]
) -> bool:
    if not node.args:
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Name) and arg.id in constants


def _call_args(node: ast.Call) -> list[ast.AST]:
    args: list[ast.AST] = list(node.args)
    args.extend(keyword.value for keyword in node.keywords)
    return args


def _is_view_or_slice(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):
        # ``unknown[:3]`` prints untrusted keys; plain ``TABLE[key]`` is often
        # a closed display-table lookup and stays a Rule B review obligation.
        return isinstance(node.slice, ast.Slice)
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in _VIEW_METHODS


def _is_repr_producing_call(node: ast.AST, constants: frozenset[str]) -> bool:
    """True when interpolating ``node`` is byte-identical to interpolating repr."""
    if _is_view_or_slice(node):
        return True
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in _CONTAINER_CALLS:
        return True
    if _is_str_join(node):
        return not _join_args_are_module_constants(node, constants)
    if isinstance(func, ast.Name) and func.id in _WRAPPER_CALLS:
        return any(
            _is_repr_producing_call(arg, constants) for arg in _call_args(node)
        )
    return False


def _rhs_renders_repr(node: ast.AST, constants: frozenset[str]) -> bool:
    if _is_repr_producing_call(node, constants):
        return True
    if isinstance(node, ast.Tuple):
        return any(_rhs_renders_repr(elt, constants) for elt in node.elts)
    return False


def _repr_sites_in(node: ast.AST, constants: frozenset[str]) -> list[int]:
    offenders: list[int] = []
    for part in ast.walk(node):
        if isinstance(part, ast.FormattedValue):
            if part.conversion in (ord("r"), ord("a")):
                offenders.append(part.lineno)
            elif _is_repr_producing_call(part.value, constants):
                offenders.append(part.lineno)
        elif isinstance(part, ast.BinOp) and isinstance(part.op, ast.Mod):
            left = part.left
            if isinstance(left, ast.Constant) and isinstance(left.value, str):
                if "%r" in left.value:
                    offenders.append(part.lineno)
                elif "%s" in left.value and _rhs_renders_repr(
                    part.right, constants
                ):
                    offenders.append(part.lineno)
        elif isinstance(part, ast.BinOp) and isinstance(part.op, ast.Add):
            if _is_repr_producing_call(
                part.left, constants
            ) or _is_repr_producing_call(part.right, constants):
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
            elif any(
                _is_repr_producing_call(arg, constants) for arg in part.args
            ):
                offenders.append(part.lineno)
    return offenders
