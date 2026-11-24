"""Context classification rules (#373). Missing gold/contexts.yaml from #371."""

from __future__ import annotations

from application.artifact.classify import (
    REASON_ROLE_DEFAULT_AMBIGUOUS,
    classify_contexts,
)
from domain.artifact.facts import ArtifactStructuralFacts
from packs.software_delivery.project.classification_rules import (
    SOFTWARE_DELIVERY_CONTEXT_RULES,
)


def test_jira_test_is_testing_by_rule() -> None:
    # AC: PROJ-140 → testing by rule. gold/contexts.yaml absent (#371).
    facts = ArtifactStructuralFacts(
        provider_type_field="Test",
        association_roles=("business",),
    )
    contexts = classify_contexts(facts, SOFTWARE_DELIVERY_CONTEXT_RULES)
    assert {(item.context, item.reason) for item in contexts} == {
        ("testing", "jira_test_to_testing")
    }


def test_openapi_is_api_contract_and_backend() -> None:
    facts = ArtifactStructuralFacts(
        path="api/openapi.yaml",
        filename="openapi.yaml",
        valid_spec_root=True,
        association_roles=("backend",),
        path_prefix_roles=(("api/", "backend"),),
    )
    contexts = classify_contexts(facts, SOFTWARE_DELIVERY_CONTEXT_RULES)
    assert {item.context for item in contexts} == {"api_contract", "backend"}


def test_operations_dockerfile_and_workflow_via_structural_facts() -> None:
    # Synced-repo AC needs #388; unit tests pass facts directly.
    docker = classify_contexts(
        ArtifactStructuralFacts(path="Dockerfile", filename="Dockerfile"),
        SOFTWARE_DELIVERY_CONTEXT_RULES,
    )
    workflow = classify_contexts(
        ArtifactStructuralFacts(
            path=".github/workflows/ci.yml", filename="ci.yml"
        ),
        SOFTWARE_DELIVERY_CONTEXT_RULES,
    )
    assert {item.context for item in docker} == {"operations"}
    assert {item.context for item in workflow} == {"operations"}


def test_frontend_tsx_via_path_prefix_role() -> None:
    facts = ArtifactStructuralFacts(
        path="components/CancelOrderButton.tsx",
        filename="CancelOrderButton.tsx",
        path_prefix_roles=(("components/", "frontend"),),
    )
    contexts = classify_contexts(facts, SOFTWARE_DELIVERY_CONTEXT_RULES)
    assert {item.context for item in contexts} == {"frontend"}


def test_multi_role_without_rule_is_ambiguous() -> None:
    facts = ArtifactStructuralFacts(
        path="shared/util.py",
        filename="util.py",
        association_roles=("backend", "frontend"),
    )
    contexts = classify_contexts(facts, SOFTWARE_DELIVERY_CONTEXT_RULES)
    assert len(contexts) == 1
    assert contexts[0].context == "backend"
    assert contexts[0].reason == REASON_ROLE_DEFAULT_AMBIGUOUS
