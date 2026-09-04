"""Shared AST helpers for architecture boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path


def imported_roots(path: Path) -> set[str]:
    """Return absolute top-level packages imported by a Python module.

    Relative imports are ignored; only absolute ``import`` / ``from`` forms
    contribute package roots.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def find_forbidden_imports(path: Path, forbidden: set[str]) -> set[str]:
    """Return forbidden package roots imported by the module."""
    return imported_roots(path) & forbidden


def _package_parts_for(path: Path) -> tuple[str, ...]:
    """Best-effort dotted package prefix for *path* based on filesystem parents.

    Walks upward while ``__init__.py`` is present so relative imports can be
    resolved against the scanned module's own package.
    """
    parts: list[str] = []
    current = path.parent
    while (current / "__init__.py").exists():
        parts.append(current.name)
        if current.parent == current:
            break
        current = current.parent
    return tuple(reversed(parts))


def _resolve_import_from_module(
    path: Path, node: ast.ImportFrom
) -> str | None:
    """Return the absolute dotted module for an ``ImportFrom`` node."""
    if node.level == 0:
        return node.module
    package = _package_parts_for(path)
    if not package:
        return node.module
    # level=1 → stay in package; level=2 → parent package; …
    up = node.level - 1
    if up >= len(package):
        base: tuple[str, ...] = ()
    else:
        base = package[: len(package) - up] if up else package
    if node.module:
        return ".".join((*base, *node.module.split("."))) if base else node.module
    return ".".join(base) if base else None


def find_forbidden_module_prefixes(path: Path, forbidden_prefixes: set[str]) -> set[str]:
    """Return imports that match a forbidden dotted prefix.

    Unlike :func:`find_forbidden_imports`, this matches full module paths (for
    example ``presentation.streamlit``), not only top-level package roots.
    Relative ``ImportFrom`` nodes are resolved against *path*'s package.
    ``from presentation import http`` is treated as ``presentation.http``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: set[str] = set()

    def _match(name: str | None) -> None:
        if not name:
            return
        for prefix in forbidden_prefixes:
            if name == prefix or name.startswith(f"{prefix}."):
                hits.add(prefix)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _match(alias.name)
        elif isinstance(node, ast.ImportFrom):
            absolute = _resolve_import_from_module(path, node)
            _match(absolute)
            # ``from presentation import http`` → presentation.http
            if node.module and node.level == 0:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    _match(f"{node.module}.{alias.name}")
    return hits


def find_non_allowed_imports(
    path: Path,
    *,
    allowed: set[str],
    forbidden: set[str] | None = None,
) -> set[str]:
    """Return imports that violate an allowlist policy.

    Absolute import roots are rejected when they are absent from *allowed* or
    present in *forbidden*. Relative imports are ignored by
    :func:`imported_roots` and therefore never reported.
    """
    blocked = forbidden or set()
    return {
        root for root in imported_roots(path) if root in blocked or root not in allowed
    }


def references_attribute(path: Path, attribute_name: str) -> bool:
    """Return True if *attribute_name* appears as a Name or Attribute in the AST.

    Comments, string literals, and docstrings do not count.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == attribute_name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == attribute_name:
            return True
    return False
