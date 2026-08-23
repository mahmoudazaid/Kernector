"""Guards the domain layer's stdlib-only, no-I/O import rule."""

from pathlib import Path

import pytest

from test.architecture.import_scan import find_forbidden_imports

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
    "application", "infrastructure", "presentation", "composition",
}


def test_domain_modules_are_discovered() -> None:
    assert DOMAIN_MODULES, f"no domain modules found under {DOMAIN_DIR}"


@pytest.mark.parametrize("module_path", DOMAIN_MODULES, ids=lambda p: p.name)
def test_domain_module_imports_no_forbidden_packages(module_path: Path) -> None:
    forbidden = find_forbidden_imports(module_path, FORBIDDEN)
    assert not forbidden, f"{module_path.name} imports {sorted(forbidden)}"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import streamlit\n", {"streamlit"}),
        ("from composition import build_app\n", {"composition"}),
    ],
)
def test_planted_domain_forbidden_import_is_detected(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    module = tmp_path / "bad_domain.py"
    module.write_text(source, encoding="utf-8")
    assert find_forbidden_imports(module, FORBIDDEN) == expected
