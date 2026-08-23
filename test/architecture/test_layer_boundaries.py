"""Guards the dependency direction between layers.

`test/domain/test_domain_boundaries.py` covers the innermost layer. This file
covers the three outward layers, so the arrows in ARCHITECTURE.md cannot quietly
reverse:

    presentation ──> composition ──> application ──> domain
                          └────────> infrastructure ─────┘
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Third-party packages that perform I/O. Only `infrastructure` may reach these.
IO_PACKAGES = {
    "langchain", "langchain_core", "langchain_openai", "openai", "ollama",
    "chromadb", "milvus", "pymilvus", "sqlalchemy", "psycopg",
    "requests", "httpx", "aiohttp",
    "numpy", "pandas",
    "dotenv",
}

LAYER_RULES: dict[str, set[str]] = {
    # Use-case orchestration: domain only. No UI, no I/O, no adapters.
    "application": {
        "infrastructure",
        "presentation",
        "composition",
        "streamlit",
        *IO_PACKAGES,
    },
    # Implements the ports. Never reaches back into the layers above it.
    "infrastructure": {
        "application",
        "presentation",
        "composition",
    },
    # The outermost edge: may wire anything inward, but is not a UI itself.
    "composition": {
        "presentation",
        "streamlit",
    },
    # The only layer allowed to import Streamlit, and it must go through
    # `composition` to reach anything that touches the outside world.
    "presentation": {
        "infrastructure",
        *IO_PACKAGES,
    },
}


def _modules(layer: str) -> list[Path]:
    return sorted((REPO_ROOT / layer).rglob("*.py"))


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


CASES = [
    (layer, module)
    for layer in LAYER_RULES
    for module in _modules(layer)
]


@pytest.mark.parametrize("layer", LAYER_RULES)
def test_layer_modules_are_discovered(layer: str) -> None:
    assert _modules(layer), f"no modules found under {layer}/"


@pytest.mark.parametrize(
    "layer,module_path", CASES, ids=[f"{layer}/{m.name}" for layer, m in CASES]
)
def test_layer_imports_no_forbidden_packages(layer: str, module_path: Path) -> None:
    forbidden = _imported_roots(module_path) & LAYER_RULES[layer]
    assert not forbidden, (
        f"{module_path.relative_to(REPO_ROOT)} imports {sorted(forbidden)}, "
        f"which {layer}/ may not depend on"
    )


def test_application_layer_never_touches_session_state() -> None:
    """AC: the application layer must not reach for Streamlit session APIs."""
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _modules("application")
        if "session_state" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"session_state referenced in {offenders}"
