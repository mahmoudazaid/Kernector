"""Guards the dependency direction between layers.

`test/domain/test_domain_boundaries.py` covers the innermost layer. This file
covers the outward layers, so the arrows in ARCHITECTURE.md cannot quietly
reverse:

    presentation ──> composition ──> application ──> domain
                          └────────> infrastructure ─────┘

Server frameworks (``fastapi`` / ``uvicorn`` / ``starlette``) may live only
under ``presentation/http/``. ``httpx`` stays in ``IO_PACKAGES`` as an HTTP
*client* library (ADR 0002 §5) — it is not a server-framework rule. ``test/``
is outside :func:`_modules`, so TestClient imports of ``httpx`` are fine.
"""

from pathlib import Path

import pytest

from test.architecture.import_scan import find_forbidden_imports

REPO_ROOT = Path(__file__).resolve().parents[2]

# Third-party packages that perform I/O. Only `infrastructure` may reach these.
IO_PACKAGES = {
    "langchain", "langchain_core", "langchain_openai", "openai", "ollama",
    "chromadb", "milvus", "pymilvus", "sqlalchemy", "psycopg",
    "requests", "httpx", "aiohttp",
    "pypdf",
    "fpdf",
    "numpy", "pandas",
    "dotenv",
}

# FastAPI stack — allowed only under presentation/http/** (path-prefix exception).
SERVER_FRAMEWORKS = {"fastapi", "uvicorn", "starlette"}

LAYER_RULES: dict[str, set[str]] = {
    # Use-case orchestration: domain only. No UI, no I/O, no adapters, no packs.
    "application": {
        "infrastructure",
        "presentation",
        "composition",
        "packs",
        *IO_PACKAGES,
        *SERVER_FRAMEWORKS,
    },
    # Implements the ports. Never reaches back into the layers above it.
    "infrastructure": {
        "application",
        "presentation",
        "composition",
        "packs",
        *SERVER_FRAMEWORKS,
    },
    # The outermost edge: may wire anything inward, but is not a UI itself.
    "composition": {
        "presentation",
        *SERVER_FRAMEWORKS,
    },
    # Presentation adapters (HTTP, CLI). Must go through composition for I/O.
    # SERVER_FRAMEWORKS are applied via :func:`_forbidden_for` with an
    # exception for presentation/http/**.
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
        *IO_PACKAGES,
        *SERVER_FRAMEWORKS,
    },
}


def _modules(layer: str) -> list[Path]:
    return sorted((REPO_ROOT / layer).rglob("*.py"))


def _under_presentation_http(module_path: Path) -> bool:
    rel = module_path.resolve().relative_to(REPO_ROOT)
    return len(rel.parts) >= 2 and rel.parts[0] == "presentation" and rel.parts[1] == "http"


def _forbidden_for(layer: str, module_path: Path) -> set[str]:
    """Return the denylist for *module_path*, including http path-prefix exception."""
    forbidden = set(LAYER_RULES[layer])
    if layer == "presentation" and not _under_presentation_http(module_path):
        forbidden |= SERVER_FRAMEWORKS
    return forbidden


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
    forbidden = find_forbidden_imports(module_path, _forbidden_for(layer, module_path))
    assert not forbidden, (
        f"{module_path.relative_to(REPO_ROOT)} imports {sorted(forbidden)}, "
        f"which {layer}/ may not depend on"
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import infrastructure\n", {"infrastructure"}),
        ("import packs\n", {"packs"}),
        ("from packs.software_delivery import scoring\n", {"packs"}),
        ("import fastapi\n", {"fastapi"}),
        ("from starlette.responses import JSONResponse\n", {"starlette"}),
        ("import uvicorn\n", {"uvicorn"}),
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
        ("import fastapi\n", {"fastapi"}),
    ],
)
def test_planted_pack_forbidden_import_is_detected(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    module = tmp_path / "bad_pack.py"
    module.write_text(source, encoding="utf-8")
    assert find_forbidden_imports(module, LAYER_RULES["packs"]) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import fastapi\n", {"fastapi"}),
        ("import uvicorn\n", {"uvicorn"}),
        ("from starlette.middleware.cors import CORSMiddleware\n", {"starlette"}),
    ],
)
def test_planted_non_http_presentation_server_framework_is_detected(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    """Server frameworks are forbidden outside presentation/http/**."""
    # Path must sit under presentation/cli so _forbidden_for applies
    # SERVER_FRAMEWORKS (tmp_path never triggers the production helper).
    module = tmp_path / "bad_presentation.py"
    module.write_text(source, encoding="utf-8")
    denylist = _forbidden_for(
        "presentation", REPO_ROOT / "presentation" / "cli" / "x.py"
    )
    assert find_forbidden_imports(module, denylist) == expected


def test_planted_presentation_http_may_import_fastapi(tmp_path: Path) -> None:
    """The path-prefix exception allows FastAPI under presentation/http/**."""
    module = tmp_path / "http_route.py"
    module.write_text("from fastapi import FastAPI\n", encoding="utf-8")
    denylist = _forbidden_for(
        "presentation", REPO_ROOT / "presentation" / "http" / "x.py"
    )
    assert find_forbidden_imports(module, denylist) == set()
    assert SERVER_FRAMEWORKS.isdisjoint(denylist)


def test_composition_does_not_reexport_raw_load_settings() -> None:
    """Presentation obtains settings only through ``load_runtime_settings``."""
    import composition

    assert not hasattr(composition, "load_settings")
    assert callable(composition.load_runtime_settings)


def test_chat_intent_imports_only_domain_and_stdlib() -> None:
    """Chat-time intent selection is pack vocabulary, so it stays pack-shaped."""
    module_path = REPO_ROOT / "packs/software_delivery/chat_intent.py"

    forbidden = find_forbidden_imports(module_path, LAYER_RULES["packs"])

    assert not forbidden, (
        f"{module_path.relative_to(REPO_ROOT)} imports {sorted(forbidden)}, "
        "which packs/ may not depend on"
    )
