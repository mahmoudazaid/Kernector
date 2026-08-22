"""Guards the domain layer's stdlib-only, no-I/O import rule."""

import ast
from pathlib import Path

import pytest

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "domain"
DOMAIN_MODULES = sorted(DOMAIN_DIR.rglob("*.py"))

FORBIDDEN = {
    # UI and web frameworks
    "streamlit", "fastapi", "starlette", "flask",
    # LLM and orchestration
    "langchain", "langchain_core", "langchain_openai", "openai", "ollama",
    # vector stores and databases
    "chromadb", "milvus", "pymilvus", "sqlite3", "sqlalchemy", "psycopg",
    # HTTP clients
    "requests", "httpx", "urllib", "http", "socket", "aiohttp",
    # filesystem
    "os", "pathlib", "shutil", "io", "open",
    # third-party modelling and numerics
    "pydantic", "numpy", "pandas",
    # outer layers
    "application", "infrastructure", "presentation",
}


def _imported_roots(path: Path) -> set[str]:
    """Top-level package names imported by a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_modules_are_discovered() -> None:
    assert DOMAIN_MODULES, f"no domain modules found under {DOMAIN_DIR}"


@pytest.mark.parametrize("module_path", DOMAIN_MODULES, ids=lambda p: p.name)
def test_domain_module_imports_no_forbidden_packages(module_path: Path) -> None:
    forbidden = _imported_roots(module_path) & FORBIDDEN
    assert not forbidden, f"{module_path.name} imports {sorted(forbidden)}"
