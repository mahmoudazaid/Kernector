"""Test Design composition stays source-neutral (#351).

Provider knowledge lives only in source adapters registered by the
composition root; the facade, chat handoff, and registry never name one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from test.architecture.import_scan import (
    find_forbidden_imports,
    find_forbidden_module_prefixes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DESIGN = REPO_ROOT / "composition" / "test_design.py"
TEST_DESIGN_SOURCES = REPO_ROOT / "composition" / "test_design_sources.py"
NEUTRAL_MODULES = (TEST_DESIGN, TEST_DESIGN_SOURCES)
GITHUB_ADAPTER_MODULES = {
    "infrastructure.connectors.github",
    "composition.test_design_github_source",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _identifiers_and_strings(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    return found


def _facade_class(tree: ast.Module) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TestDesignFacade"
    )


@pytest.mark.parametrize("module_path", NEUTRAL_MODULES, ids=lambda p: p.name)
def test_neutral_modules_do_not_import_github_adapters(module_path: Path) -> None:
    assert not find_forbidden_module_prefixes(module_path, GITHUB_ADAPTER_MODULES)
    github_names = {
        name for name in _imported_names(_tree(module_path)) if "github" in name.casefold()
    }
    assert not github_names, f"{module_path.name} imports {sorted(github_names)}"


@pytest.mark.parametrize("module_path", NEUTRAL_MODULES, ids=lambda p: p.name)
def test_neutral_modules_have_no_github_provider_literal(module_path: Path) -> None:
    literals = {
        node.value
        for node in ast.walk(_tree(module_path))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip().casefold() == "github"
    }
    assert not literals, f"{module_path.name} hard-codes a provider literal"


def test_facade_class_has_no_github_tokens() -> None:
    tokens = {
        token
        for token in _identifiers_and_strings(_facade_class(_tree(TEST_DESIGN)))
        if "github" in token.casefold()
    }
    assert not tokens, f"TestDesignFacade references {sorted(tokens)}"


def test_test_design_pack_stays_independent_and_provider_literal_free() -> None:
    root = REPO_ROOT / "packs" / "software_delivery" / "test_design"
    for module_path in sorted(root.rglob("*.py")):
        rel = module_path.relative_to(REPO_ROOT)
        assert not find_forbidden_imports(
            module_path, {"application", "composition", "infrastructure", "presentation"}
        ), f"{rel} imports an outer layer"
        assert "github" not in module_path.read_text(encoding="utf-8").casefold(), (
            f"{rel} names a concrete provider"
        )


def test_planted_github_import_in_facade_module_is_detected(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        "from composition.test_design_github_source import GitHubTestDesignSource\n",
        encoding="utf-8",
    )

    assert find_forbidden_module_prefixes(planted, GITHUB_ADAPTER_MODULES)
    assert "GitHubTestDesignSource" in _imported_names(_tree(planted))
