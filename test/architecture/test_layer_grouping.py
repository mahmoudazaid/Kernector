"""Modules are grouped by concern in every layer (ADR 0008).

The grandfathered sets list today's layer-root modules. They may only shrink:
a new root module fails, and a moved module must be removed from its set.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = "docs/adr/0008-group-modules-by-concern.md"

GRANDFATHERED_ROOT_MODULES: dict[str, frozenset[str]] = {
    "domain": frozenset(
        {
            "artifacts",
            "errors",
            "knowledge",
            "model_settings",
            "models",
            "ports",
            "response_feedback",
            "thread_memory",
            "tool_approval",
            "validation",
        }
    ),
    "application": frozenset(
        {
            "ask_general",
            "ask_knowledge",
            "ask_knowledge_with_agent",
            "ask_service",
            "chunking",
            "citations",
            "contracts",
            "decide_tool_approval",
            "errors",
            "evaluate_knowledge",
            "evaluate_rag",
            "evaluation_contracts",
            "general_answer_policy",
            "grounded_rag_policy",
            "hybrid_fusion",
            "ingest_knowledge",
            "input_safety",
            "invoke_tool",
            "manage_documents",
            "markdown",
            "observability",
            "observed_rag",
            "rag_judge_contracts",
            "rag_judge_policy",
            "response_style_policy",
            "retrieval_citation_channel",
            "retrieve_knowledge",
            "retrieve_knowledge_tool",
            "rewrite_and_retrieve",
            "run_tool_agent",
            "runtime_settings",
            "submit_response_feedback",
            "sync_connector",
            "thread_memory",
            "tool_approval",
            "turn_routing",
            "untrusted_text",
        }
    ),
    "infrastructure": frozenset({"config"}),
    "presentation": frozenset({"failure_messages"}),
    "composition": frozenset(
        {"container", "documents", "errors", "evaluate", "logging_config"}
    ),
    "packs": frozenset(),
    "packs/software_delivery": frozenset(
        {
            "chat_intent",
            "contracts",
            "errors",
            "limits",
            "registration",
        }
    ),
}

CONTAINER = REPO_ROOT / "composition" / "container.py"
PROVIDER_CONNECTORS = "infrastructure.connectors"
GRANDFATHERED_CONTAINER_CONNECTOR_IMPORTS = frozenset(
    {
        "infrastructure.connectors.google_drive.artifact_uploader",
        "infrastructure.connectors.google_drive.oauth",
    }
)


def _root_modules(layer: str) -> set[str]:
    return {
        path.stem
        for path in (REPO_ROOT / layer).glob("*.py")
        if path.name != "__init__.py"
    }


def _layer_roots() -> list[str]:
    packs = sorted(
        f"packs/{path.name}"
        for path in (REPO_ROOT / "packs").iterdir()
        if (path / "__init__.py").exists()
    )
    return ["domain", "application", "infrastructure", "presentation", "composition", "packs", *packs]


@pytest.mark.parametrize("layer", _layer_roots())
def test_no_new_modules_at_layer_roots(layer: str) -> None:
    allowed = GRANDFATHERED_ROOT_MODULES.get(layer, frozenset())
    added = sorted(_root_modules(layer) - allowed)

    assert not added, (
        f"New module(s) at {layer}/ root: {added}. "
        f"Put them in a concern package ({ADR})."
    )


@pytest.mark.parametrize("layer", sorted(GRANDFATHERED_ROOT_MODULES))
def test_grandfathered_root_modules_only_shrink(layer: str) -> None:
    stale = sorted(GRANDFATHERED_ROOT_MODULES[layer] - _root_modules(layer))

    assert not stale, f"Remove moved module(s) {stale} from the {layer} allowlist."


def _container_connector_imports() -> set[str]:
    tree = ast.parse(CONTAINER.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
    return {
        name
        for name in modules
        if name == PROVIDER_CONNECTORS or name.startswith(f"{PROVIDER_CONNECTORS}.")
    }


def test_container_does_not_build_provider_connectors() -> None:
    added = sorted(
        _container_connector_imports() - GRANDFATHERED_CONTAINER_CONNECTOR_IMPORTS
    )

    assert not added, (
        f"composition/container.py imports {added}. Move provider construction "
        f"into its concern package and call one builder ({ADR})."
    )


def test_grandfathered_container_connector_imports_only_shrink() -> None:
    stale = sorted(
        GRANDFATHERED_CONTAINER_CONNECTOR_IMPORTS - _container_connector_imports()
    )

    assert not stale, f"Remove {stale} from the container connector allowlist."
