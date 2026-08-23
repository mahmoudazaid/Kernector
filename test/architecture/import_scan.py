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
