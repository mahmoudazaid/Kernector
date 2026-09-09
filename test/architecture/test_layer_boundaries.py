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

from test.architecture.import_scan import (
    find_forbidden_imports,
    find_forbidden_module_prefixes,
)

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
    "google",
    "googleapiclient",
    "httplib2",
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
        ("import google\n", {"google"}),
        ("from googleapiclient.discovery import build\n", {"googleapiclient"}),
        ("import httplib2\n", {"httplib2"}),
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
        ("import google\n", {"google"}),
        ("from googleapiclient.discovery import build\n", {"googleapiclient"}),
        ("import httplib2\n", {"httplib2"}),
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
        ("import google\n", {"google"}),
        ("from googleapiclient.http import MediaIoBaseDownload\n", {"googleapiclient"}),
        ("import httplib2\n", {"httplib2"}),
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


# Build tooling whose job *is* to serialize another adapter's schema, so the
# peer-import rule below cannot apply. Keep this list empty of runtime modules.
PEER_IMPORT_EXEMPT = {Path("presentation/cli/export_openapi.py")}


def test_presentation_adapters_are_mutually_isolated() -> None:
    """Keep each UI replaceable: adapters must not import each other."""
    for adapter, forbidden in (
        ("http", "presentation.cli"),
        ("cli", "presentation.http"),
    ):
        root = REPO_ROOT / "presentation" / adapter
        assert root.is_dir(), f"presentation/{adapter} no longer exists"
        for path in sorted(root.rglob("*.py")):
            if path.relative_to(REPO_ROOT) in PEER_IMPORT_EXEMPT:
                continue
            hits = find_forbidden_module_prefixes(path, {forbidden})
            assert not hits, (
                f"{path.relative_to(REPO_ROOT)} imports {forbidden}"
            )


def test_peer_import_exemptions_all_exist() -> None:
    """A stale exemption would silently widen the isolation rule."""
    for relative in PEER_IMPORT_EXEMPT:
        assert (REPO_ROOT / relative).is_file(), f"{relative} no longer exists"


def _plant_presentation_module(tmp_path: Path, adapter: str, source: str) -> Path:
    """Write *source* into a fake ``presentation/<adapter>`` package.

    ``_package_parts_for`` walks ``__init__.py`` upward, so relative imports
    only resolve inside a real package. Building it under ``tmp_path`` keeps
    the architecture suite from writing into ``REPO_ROOT``.
    """
    package = tmp_path / "presentation" / adapter
    package.mkdir(parents=True)
    (tmp_path / "presentation" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    module = package / "leak.py"
    module.write_text(source, encoding="utf-8")
    return module


@pytest.mark.parametrize(
    "source",
    [
        "import presentation.http\n",
        "from presentation.http import deps\n",
        "from presentation import http\n",
        "from .. import http\n",
        "from ..http import deps\n",
    ],
)
def test_planted_peer_adapter_import_is_detected(tmp_path: Path, source: str) -> None:
    """Every import form that names ``presentation.http`` must be caught."""
    module = _plant_presentation_module(tmp_path, "cli", source)

    hits = find_forbidden_module_prefixes(module, {"presentation.http"})

    assert hits == {"presentation.http"}


def test_planted_relative_import_above_package_root_is_not_resolved(
    tmp_path: Path,
) -> None:
    """A level that escapes the package resolves to nothing, not a bare name."""
    module = _plant_presentation_module(
        tmp_path, "cli", "from ....http import deps\n"
    )

    assert find_forbidden_module_prefixes(module, {"presentation.http"}) == set()
    assert find_forbidden_module_prefixes(module, {"http"}) == set()


def test_composition_and_presentation_do_not_import_test() -> None:
    """Eval and other production wiring must not import test doubles."""
    for layer in ("composition", "presentation"):
        for module_path in _modules(layer):
            hits = find_forbidden_imports(module_path, {"test"})
            assert not hits, (
                f"{module_path.relative_to(REPO_ROOT)} imports test/"
            )


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


def test_only_infrastructure_imports_google_drive_client() -> None:
    """Google client packages stay behind the infrastructure connector adapter."""
    google_roots = {"google", "googleapiclient"}
    for layer in ("domain", "application", "presentation", "packs"):
        for module_path in _modules(layer):
            hits = find_forbidden_imports(module_path, google_roots)
            assert not hits, (
                f"{module_path.relative_to(REPO_ROOT)} imports {sorted(hits)}"
            )
    drive = REPO_ROOT / "infrastructure" / "connectors" / "google_drive.py"
    imported = find_forbidden_imports(drive, google_roots)
    assert imported == google_roots


def test_drive_sync_cli_reaches_the_connector_only_through_composition() -> None:
    cli = REPO_ROOT / "presentation" / "cli" / "sync_google_drive.py"
    assert not find_forbidden_imports(
        cli, {"infrastructure", "google", "googleapiclient"}
    )
    source = cli.read_text(encoding="utf-8")
    assert "from composition import" in source
    assert "sync_google_drive" in source
