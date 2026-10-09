"""Project Intelligence stays pack- and provider-neutral (#372, ADR 0011).

Context and role tokens belong to packs; connector scope kinds belong to
infrastructure adapters registered by the composition root.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test.architecture.import_scan import imported_roots

REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_PROJECT = REPO_ROOT / "domain" / "project"
NEUTRAL_ROOTS = (
    DOMAIN_PROJECT,
    REPO_ROOT / "application" / "project",
    REPO_ROOT / "infrastructure" / "project",
    REPO_ROOT / "composition" / "project",
)
ABOVE_INFRASTRUCTURE = (
    *sorted(DOMAIN_PROJECT.rglob("*.py")),
    *sorted((REPO_ROOT / "application" / "project").rglob("*.py")),
    REPO_ROOT / "presentation" / "http" / "routes" / "projects.py",
    REPO_ROOT / "composition" / "mcp" / "project_list.py",
)
CONTEXT_TOKENS = frozenset(
    {
        "business",
        "api_contract",
        "frontend",
        "backend",
        "operations",
        "testing",
        "documentation",
    }
)
PROVIDER_LITERALS = frozenset({"repo", "project_key", "github", "jira"})
PROVIDER_NAME_FRAGMENTS = ("github", "jira")


def _modules(roots: tuple[Path, ...]) -> list[Path]:
    return [path for root in roots for path in sorted(root.rglob("*.py"))]


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value.strip().casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _context_literals(path: Path) -> set[str]:
    return _string_constants(path) & CONTEXT_TOKENS


def _provider_tokens(path: Path) -> set[str]:
    literals = _string_constants(path) & PROVIDER_LITERALS
    names = {
        name
        for name in _identifiers(path)
        if any(fragment in name.casefold() for fragment in PROVIDER_NAME_FRAGMENTS)
    }
    return literals | names


@pytest.mark.parametrize(
    "module_path",
    sorted(DOMAIN_PROJECT.rglob("*.py")),
    ids=lambda p: p.name,
)
def test_domain_project_imports_stdlib_and_domain_only(module_path: Path) -> None:
    allowed = set(sys.stdlib_module_names) | {"domain", "__future__"}

    assert imported_roots(module_path) <= allowed


@pytest.mark.parametrize(
    "module_path", _modules(NEUTRAL_ROOTS), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_project_modules_have_no_context_literals(module_path: Path) -> None:
    assert not _context_literals(module_path)


@pytest.mark.parametrize(
    "module_path", ABOVE_INFRASTRUCTURE, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_project_modules_above_infrastructure_have_no_provider_tokens(
    module_path: Path,
) -> None:
    assert not _provider_tokens(module_path)


def test_planted_context_and_provider_literals_are_detected(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        "from infrastructure.connectors.github.project_scope import REPO_SCOPE_KIND\n"
        'ROLE = "backend"\n'
        'KIND = "repo"\n',
        encoding="utf-8",
    )

    assert _context_literals(planted) == {"backend"}
    assert {
        "repo",
        "infrastructure.connectors.github.project_scope",
    } <= _provider_tokens(planted)


def test_project_wiring_without_packs_does_not_import_packs() -> None:
    script = r"""
import sys
from dataclasses import replace

import infrastructure.config as config

config.load_dotenv = lambda *a, **k: False

from composition.mcp.project_list import ProjectListTool
from composition.project.container import build_project_use_cases
from infrastructure.config import DomainToolSettings, load_settings
from presentation.http.routes import projects

settings = replace(
    load_settings(),
    domain_tools=DomainToolSettings(enabled_packs=()),
)
use_cases = build_project_use_cases(settings)
ProjectListTool(use_cases.list).run({})
assert not any(name == "packs" or name.startswith("packs.") for name in sys.modules)
print("ok", flush=True)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "DOMAIN_TOOL_PACKS": "",
        "PYTHONUNBUFFERED": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "ok" in completed.stdout
