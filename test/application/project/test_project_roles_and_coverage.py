"""Role validation and structural context coverage (#372)."""

from __future__ import annotations

import pytest

from application.project.associations import (
    AssociateSource,
    AssociateSourceRequest,
    ConfirmAssociation,
    ConfirmAssociationRequest,
)
from application.project.coverage import ProjectContextCoverage
from application.project.projects import GetProject
from domain.project.errors import ProjectInputError
from domain.project.models import (
    AssociationState,
    ContextAssociationStatus,
    Project,
    SourceAssociation,
    SourceScope,
)
from packs.software_delivery.registration import build_context_vocabulary
from test.application.project.project_fakes import InMemoryProjectStore

JIRA_PROJ = SourceScope("jira-1", "project_key", "PROJ")
WEB = SourceScope("gh-1", "repo", "acme/proj-web")
ORDERS = SourceScope("gh-1", "repo", "acme/proj-orders")
TESTS = SourceScope("gh-1", "repo", "acme/proj-tests")
DOCS = SourceScope("gh-1", "repo", "acme/proj-docs")
VOCABULARY = build_context_vocabulary()


@pytest.fixture
def store() -> InMemoryProjectStore:
    store = InMemoryProjectStore()
    with store.transaction() as tx:
        tx.projects.add(Project("prj_proj", "Order Intake", "proj", 1))
    return store


def _associate(
    store: InMemoryProjectStore,
    scope: SourceScope,
    roles: tuple[str, ...],
    vocabulary: object | None = VOCABULARY,
) -> SourceAssociation:
    return AssociateSource(store=store, vocabulary=vocabulary).execute(
        AssociateSourceRequest("prj_proj", scope, roles, "operator")
    )


def _suggest(store: InMemoryProjectStore, scope: SourceScope) -> None:
    with store.transaction() as tx:
        tx.associations.add(
            SourceAssociation(
                "prj_proj", scope, (), AssociationState.SUGGESTED, (), "evidence", 1
            )
        )


def test_pack_registers_the_seven_contexts_in_order() -> None:
    assert VOCABULARY.contexts == (
        "business",
        "api_contract",
        "frontend",
        "backend",
        "operations",
        "testing",
        "documentation",
    )


def test_unknown_role_is_rejected(store: InMemoryProjectStore) -> None:
    with pytest.raises(ProjectInputError):
        _associate(store, ORDERS, ("backend", "database"))

    with store.read() as tx:
        assert tx.associations.get("prj_proj", ORDERS) is None


def test_scope_can_hold_several_roles(store: InMemoryProjectStore) -> None:
    association = _associate(store, ORDERS, ("backend", "api_contract"))

    assert association.roles == ("backend", "api_contract")


def test_roles_need_a_registered_vocabulary(store: InMemoryProjectStore) -> None:
    with pytest.raises(ProjectInputError):
        _associate(store, ORDERS, ("backend",), vocabulary=None)

    assert _associate(store, ORDERS, (), vocabulary=None).roles == ()


def test_confirm_validates_new_roles(store: InMemoryProjectStore) -> None:
    _suggest(store, DOCS)
    confirm = ConfirmAssociation(store=store, vocabulary=VOCABULARY)

    with pytest.raises(ProjectInputError):
        confirm.execute(ConfirmAssociationRequest("prj_proj", DOCS, 1, roles=("wiki",)))
    confirmed = confirm.execute(
        ConfirmAssociationRequest("prj_proj", DOCS, 1, roles=("documentation",))
    )

    assert confirmed.roles == ("documentation",)


def test_associate_without_roles_is_rejected_with_a_vocabulary(
    store: InMemoryProjectStore,
) -> None:
    associate = AssociateSource(
        store=store, vocabulary=VOCABULARY, component_forming_kinds=frozenset({"repo"})
    )

    with pytest.raises(ProjectInputError):
        associate.execute(AssociateSourceRequest("prj_proj", ORDERS, (), "operator"))

    with store.read() as tx:
        assert tx.associations.get("prj_proj", ORDERS) is None
        assert tx.components.for_project("prj_proj") == ()


@pytest.mark.parametrize("roles", [None, ()], ids=["omitted", "empty"])
def test_confirming_a_suggestion_without_roles_is_rejected_with_a_vocabulary(
    store: InMemoryProjectStore, roles: tuple[str, ...] | None
) -> None:
    _suggest(store, DOCS)
    with store.read() as tx:
        suggestion = tx.associations.get("prj_proj", DOCS)
    confirm = ConfirmAssociation(
        store=store, vocabulary=VOCABULARY, component_forming_kinds=frozenset({"repo"})
    )

    with pytest.raises(ProjectInputError):
        confirm.execute(ConfirmAssociationRequest("prj_proj", DOCS, 1, roles=roles))

    assert suggestion is not None
    assert suggestion.roles == ()
    with store.read() as tx:
        assert tx.associations.get("prj_proj", DOCS) == suggestion
        assert tx.components.for_project("prj_proj") == ()


def test_confirming_without_roles_is_allowed_without_a_vocabulary(
    store: InMemoryProjectStore,
) -> None:
    _suggest(store, DOCS)

    confirmed = ConfirmAssociation(store=store, vocabulary=None).execute(
        ConfirmAssociationRequest("prj_proj", DOCS, 1)
    )

    assert confirmed.state is AssociationState.CONFIRMED
    assert confirmed.roles == ()


def test_coverage_reports_every_registered_context(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, JIRA_PROJ, ("business",))
    _associate(store, WEB, ("frontend",))
    _associate(store, ORDERS, ("backend", "api_contract"))
    _associate(store, TESTS, ("testing",))

    report = ProjectContextCoverage(store=store, vocabulary=VOCABULARY).execute(
        "prj_proj"
    )

    assert [(c.context, c.status) for c in report] == [
        ("business", ContextAssociationStatus.ASSOCIATED),
        ("api_contract", ContextAssociationStatus.ASSOCIATED),
        ("frontend", ContextAssociationStatus.ASSOCIATED),
        ("backend", ContextAssociationStatus.ASSOCIATED),
        ("operations", ContextAssociationStatus.NOT_ASSOCIATED),
        ("testing", ContextAssociationStatus.ASSOCIATED),
        ("documentation", ContextAssociationStatus.NOT_ASSOCIATED),
    ]
    by_context = {c.context: c.scopes for c in report}
    assert by_context["backend"] == (ORDERS,)
    assert by_context["business"] == (JIRA_PROJ,)
    assert by_context["operations"] == ()


def test_suggested_role_does_not_count(store: InMemoryProjectStore) -> None:
    with store.transaction() as tx:
        tx.associations.add(
            SourceAssociation(
                "prj_proj",
                DOCS,
                ("documentation",),
                AssociationState.SUGGESTED,
                (),
                "evidence",
                1,
            )
        )

    report = ProjectContextCoverage(store=store, vocabulary=VOCABULARY).execute(
        "prj_proj"
    )

    documentation = next(c for c in report if c.context == "documentation")
    assert documentation.status is ContextAssociationStatus.NOT_ASSOCIATED


def test_coverage_is_empty_without_vocabulary(store: InMemoryProjectStore) -> None:
    _associate(store, ORDERS, (), vocabulary=None)

    assert ProjectContextCoverage(store=store, vocabulary=None).execute("prj_proj") == ()


def test_project_detail_includes_coverage(store: InMemoryProjectStore) -> None:
    _associate(store, ORDERS, ("backend",))

    detail = GetProject(store=store, vocabulary=VOCABULARY).execute("prj_proj")

    assert len(detail.context_coverage) == len(VOCABULARY.contexts)
    backend = next(c for c in detail.context_coverage if c.context == "backend")
    assert backend.scopes == (ORDERS,)
