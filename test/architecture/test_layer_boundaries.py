"""Guards the dependency direction between layers.

`test/domain/test_domain_boundaries.py` covers the innermost layer. This file
covers the outward layers, so the arrows in ARCHITECTURE.md cannot quietly
reverse:

    presentation ──> composition ──> application ──> domain
                          └────────> infrastructure ─────┘
"""

from pathlib import Path

import pytest

from test.architecture.import_scan import (
    find_forbidden_imports,
    references_attribute,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Third-party packages that perform I/O. Only `infrastructure` may reach these.
IO_PACKAGES = {
    "langchain", "langchain_core", "langchain_openai", "openai", "ollama",
    "chromadb", "milvus", "pymilvus", "sqlalchemy", "psycopg",
    "requests", "httpx", "aiohttp",
    "pypdf",
    "numpy", "pandas",
    "dotenv",
}

LAYER_RULES: dict[str, set[str]] = {
    # Use-case orchestration: domain only. No UI, no I/O, no adapters, no packs.
    "application": {
        "infrastructure",
        "presentation",
        "composition",
        "packs",
        "streamlit",
        *IO_PACKAGES,
    },
    # Implements the ports. Never reaches back into the layers above it.
    "infrastructure": {
        "application",
        "presentation",
        "composition",
        "packs",
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
        "packs",
        *IO_PACKAGES,
    },
    # Optional executable domain packs: domain + stdlib only.
    "packs": {
        "application",
        "infrastructure",
        "presentation",
        "composition",
        "streamlit",
        *IO_PACKAGES,
    },
}


def _modules(layer: str) -> list[Path]:
    return sorted((REPO_ROOT / layer).rglob("*.py"))


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
    forbidden = find_forbidden_imports(module_path, LAYER_RULES[layer])
    assert not forbidden, (
        f"{module_path.relative_to(REPO_ROOT)} imports {sorted(forbidden)}, "
        f"which {layer}/ may not depend on"
    )


def test_application_layer_never_touches_session_state() -> None:
    """AC: the application layer must not reach for Streamlit session APIs."""
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _modules("application")
        if references_attribute(path, "session_state")
    ]
    assert not offenders, f"session_state referenced in {offenders}"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import infrastructure\n", {"infrastructure"}),
        ("from streamlit import session_state\n", {"streamlit"}),
        ("import packs\n", {"packs"}),
        ("from packs.software_delivery import scoring\n", {"packs"}),
    ],
)
def test_planted_application_forbidden_import_is_detected(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    module = tmp_path / "bad_application.py"
    module.write_text(source, encoding="utf-8")
    assert find_forbidden_imports(module, LAYER_RULES["application"]) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import application\n", {"application"}),
        ("import infrastructure\n", {"infrastructure"}),
        ("from composition.tool_registry import build_tool_registry\n", {"composition"}),
        ("import streamlit\n", {"streamlit"}),
    ],
)
def test_planted_pack_forbidden_import_is_detected(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    module = tmp_path / "bad_pack.py"
    module.write_text(source, encoding="utf-8")
    assert find_forbidden_imports(module, LAYER_RULES["packs"]) == expected


def test_planted_application_session_state_attribute_is_detected(tmp_path: Path) -> None:
    module = tmp_path / "bad_session.py"
    module.write_text("import streamlit as st\nst.session_state['x'] = 1\n", encoding="utf-8")
    assert references_attribute(module, "session_state")


def test_planted_application_session_state_name_is_detected(tmp_path: Path) -> None:
    module = tmp_path / "bad_from_import.py"
    module.write_text("from streamlit import session_state\nsession_state['x'] = 1\n", encoding="utf-8")
    assert references_attribute(module, "session_state")


def test_session_state_in_comments_and_strings_is_ignored(tmp_path: Path) -> None:
    module = tmp_path / "doc_only.py"
    module.write_text(
        '"""The application must not use session_state."""\n'
        "# session_state is forbidden here.\n"
        'message = "session_state"\n',
        encoding="utf-8",
    )
    assert not references_attribute(module, "session_state")


def test_composition_does_not_reexport_raw_load_settings() -> None:
    """Presentation obtains settings only through ``load_runtime_settings``."""
    import composition

    assert not hasattr(composition, "load_settings")
    assert callable(composition.load_runtime_settings)
