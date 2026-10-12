"""Default components, path-prefix resolution and operator edits (#372)."""

from __future__ import annotations

import pytest

from application.project.associations import (
    AssociateSource,
    AssociateSourceRequest,
    ConfirmAssociation,
    ConfirmAssociationRequest,
    RemoveAssociation,
    RemoveAssociationRequest,
)
from application.project.components import (
    AssignComponent,
    AssignComponentRequest,
    MergeComponents,
    MergeComponentsRequest,
    ResolveComponentsForSource,
    SplitComponent,
    SplitComponentRequest,
)
from domain.knowledge import SourceReference
from domain.project.errors import (
    AssociationExistsError,
    ProjectInputError,
    ProjectRecordVersionConflictError,
)
from domain.project.models import (
    COMPONENT_REASON_ASSOCIATION_DEFAULT,
    COMPONENT_REASON_OPERATOR,
    AssociationState,
    ComponentMember,
    ComponentResolutionStatus,
    Project,
    ProjectComponent,
    SourceAssociation,
    SourceScope,
)
from infrastructure.connectors.github.project_scope import GitHubSourceScopeResolver
from infrastructure.connectors.jira.project_scope import JiraSourceScopeResolver
from test.application.project.project_fakes import (
    InMemoryProjectStore,
    InjectedFailure,
    catalog_document,
)
from test.document_doubles import InMemoryDocumentCatalog

KINDS = frozenset({"repo"})
WEB = SourceScope("gh-1", "repo", "acme/oie-web")
ORDERS = SourceScope("gh-1", "repo", "acme/oie-orders")
TESTS = SourceScope("gh-1", "repo", "acme/oie-tests")
E2E = SourceScope("gh-1", "repo", "acme/oie-e2e")
MONO = SourceScope("gh-1", "repo", "acme/mono")
JIRA_OIE = SourceScope("jira-1", "project_key", "OIE")
RESOLVERS = {"github": GitHubSourceScopeResolver(), "jira": JiraSourceScopeResolver()}


@pytest.fixture
def store() -> InMemoryProjectStore:
    store = InMemoryProjectStore()
    with store.transaction() as tx:
        tx.projects.add(Project("prj_oie", "Order Intake", "oie", 1))
        tx.projects.add(Project("prj_pay", "Payments", "pay", 1))
    return store


def _associate(
    store: InMemoryProjectStore,
    scope: SourceScope,
    project_id: str = "prj_oie",
    acknowledged: frozenset[str] = frozenset(),
) -> SourceAssociation:
    return AssociateSource(store=store, component_forming_kinds=KINDS).execute(
        AssociateSourceRequest(project_id, scope, (), "operator", acknowledged)
    )


def _suggest(store: InMemoryProjectStore, scope: SourceScope) -> None:
    with store.transaction() as tx:
        tx.associations.add(
            SourceAssociation(
                "prj_oie", scope, (), AssociationState.SUGGESTED, (), "evidence", 1
            )
        )


def _confirm(store: InMemoryProjectStore, scope: SourceScope, version: int = 1):
    return ConfirmAssociation(store=store, component_forming_kinds=KINDS).execute(
        ConfirmAssociationRequest("prj_oie", scope, version)
    )


def _components(store: InMemoryProjectStore, project_id: str = "prj_oie"):
    with store.read() as tx:
        return tx.components.for_project(project_id)


def _component_for(store: InMemoryProjectStore, scope: SourceScope) -> ProjectComponent:
    return next(
        c for c in _components(store) if any(m.scope == scope for m in c.members)
    )


def _resolve(store: InMemoryProjectStore, *source_ids: str):
    catalog = InMemoryDocumentCatalog()
    for source_id in source_ids:
        catalog.upsert(catalog_document(source_id, "github", "gh-1"))
    resolve = ResolveComponentsForSource(
        store=store, catalog=catalog, resolvers=RESOLVERS
    )
    return {
        source_id: resolve.execute(SourceReference(source_id, "github"))
        for source_id in source_ids
    }


def test_confirming_repositories_creates_default_components(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, WEB)
    _associate(store, ORDERS)
    _suggest(store, TESTS)
    _confirm(store, TESTS)
    _associate(store, E2E)
    _associate(store, JIRA_OIE)

    components = _components(store)

    assert len(components) == 4
    assert {c.reason for c in components} == {COMPONENT_REASON_ASSOCIATION_DEFAULT}
    assert {c.members for c in components} == {
        (ComponentMember(scope, ""),) for scope in (WEB, ORDERS, TESTS, E2E)
    }


def test_failed_default_component_rolls_back_the_confirmation(
    store: InMemoryProjectStore,
) -> None:
    _suggest(store, TESTS)
    store.fail_on.add("components.add")

    with pytest.raises(InjectedFailure):
        _confirm(store, TESTS)

    with store.read() as tx:
        association = tx.associations.get("prj_oie", TESTS)
    assert association.state is AssociationState.SUGGESTED
    assert association.version == 1
    assert _components(store) == ()


def test_remove_deletes_members_and_empty_components(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, ORDERS)
    _associate(store, TESTS)
    tests = _component_for(store, TESTS)
    orders = _component_for(store, ORDERS)
    AssignComponent(store=store).execute(
        AssignComponentRequest(
            "prj_oie",
            orders.component_id,
            orders.version,
            ComponentMember(TESTS, ""),
            source_component_id=tests.component_id,
            source_expected_version=tests.version,
        )
    )

    RemoveAssociation(store=store).execute(
        RemoveAssociationRequest("prj_oie", TESTS, expected_version=1)
    )

    (remaining,) = _components(store)
    assert remaining.members == (ComponentMember(ORDERS, ""),)
    resolutions = _resolve(store, "acme/oie-tests:t/test_a.py")
    assert resolutions["acme/oie-tests:t/test_a.py"] == ()


def test_failure_mid_remove_leaves_everything_unchanged(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, ORDERS)
    before = _components(store)
    store.fail_on.add("components.delete")

    with pytest.raises(InjectedFailure):
        RemoveAssociation(store=store).execute(
            RemoveAssociationRequest("prj_oie", ORDERS, expected_version=1)
        )

    with store.read() as tx:
        assert tx.associations.get("prj_oie", ORDERS) is not None
    assert _components(store) == before


def _split(store: InMemoryProjectStore, prefix: str, name: str) -> ProjectComponent:
    base = _component_for(store, MONO)
    return SplitComponent(store=store).execute(
        SplitComponentRequest(
            "prj_oie", base.component_id, base.version, MONO, prefix, name
        )
    )


def test_monorepo_resolves_by_longest_directory_prefix(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, MONO)
    root = _component_for(store, MONO)
    web = _split(store, "web/", "web")
    services = _split(store, "services", "services")

    resolved = _resolve(
        store,
        "acme/mono:web/a.tsx",
        "acme/mono:services/b.py",
        "acme/mono:website/x",
        "acme/mono:README.md",
        "acme/mono:web/../secret",
    )

    def single(source_id: str):
        (resolution,) = resolved[source_id]
        return resolution.status, resolution.component_ids

    resolved_status = ComponentResolutionStatus.RESOLVED
    assert single("acme/mono:web/a.tsx") == (resolved_status, (web.component_id,))
    assert single("acme/mono:services/b.py") == (
        resolved_status,
        (services.component_id,),
    )
    assert single("acme/mono:website/x") == (resolved_status, (root.component_id,))
    assert single("acme/mono:README.md") == (resolved_status, (root.component_id,))
    assert single("acme/mono:web/../secret") == (
        ComponentResolutionStatus.INVALID_PATH,
        (),
    )


def test_unassigned_without_a_matching_member(store: InMemoryProjectStore) -> None:
    _associate(store, MONO)
    root = _component_for(store, MONO)
    _split(store, "web", "web")
    with store.transaction() as tx:
        tx.components.delete("prj_oie", root.component_id, expected_version=2)

    (resolution,) = _resolve(store, "acme/mono:docs/a.md")["acme/mono:docs/a.md"]

    assert resolution.status is ComponentResolutionStatus.UNASSIGNED


def test_shared_scope_resolves_one_component_per_project(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, MONO)
    _associate(store, MONO, "prj_pay", frozenset({"prj_oie"}))

    resolved = _resolve(store, "acme/mono:a.py")["acme/mono:a.py"]

    assert [r.project_id for r in resolved] == ["prj_oie", "prj_pay"]
    assert all(r.status is ComponentResolutionStatus.RESOLVED for r in resolved)


def test_split_rules(store: InMemoryProjectStore) -> None:
    _associate(store, MONO)
    _split(store, "web", "web")
    base = _component_for(store, MONO)

    with pytest.raises(ProjectRecordVersionConflictError):
        SplitComponent(store=store).execute(
            SplitComponentRequest("prj_oie", base.component_id, 99, MONO, "api", "api")
        )
    with pytest.raises(AssociationExistsError):
        _split(store, "web", "again")
    with pytest.raises(ProjectInputError):
        _split(store, "../x", "bad")


def test_failure_mid_split_leaves_everything_unchanged(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, MONO)
    before = _components(store)
    store.fail_on.add("components.update")

    with pytest.raises(InjectedFailure):
        _split(store, "web", "web")

    assert _components(store) == before


def test_merge_needs_every_version(store: InMemoryProjectStore) -> None:
    _associate(store, WEB)
    _associate(store, ORDERS)
    web, orders = _component_for(store, WEB), _component_for(store, ORDERS)
    merge = MergeComponents(store=store)

    with pytest.raises(ProjectRecordVersionConflictError):
        merge.execute(
            MergeComponentsRequest(
                "prj_oie",
                ((web.component_id, web.version), (orders.component_id, 7)),
                "oie",
            )
        )
    assert len(_components(store)) == 2
    merged = merge.execute(
        MergeComponentsRequest(
            "prj_oie",
            ((web.component_id, web.version), (orders.component_id, orders.version)),
            "oie",
        )
    )

    assert _components(store) == (merged,)
    assert merged.members == (ComponentMember(WEB, ""), ComponentMember(ORDERS, ""))
    assert merged.reason == COMPONENT_REASON_OPERATOR


def test_assign_needs_versions_and_the_source_component(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, ORDERS)
    _associate(store, TESTS)
    orders, tests = _component_for(store, ORDERS), _component_for(store, TESTS)
    assign = AssignComponent(store=store)
    member = ComponentMember(TESTS, "")

    with pytest.raises(AssociationExistsError):
        assign.execute(
            AssignComponentRequest(
                "prj_oie", orders.component_id, orders.version, member
            )
        )
    with pytest.raises(ProjectRecordVersionConflictError):
        assign.execute(
            AssignComponentRequest(
                "prj_oie",
                orders.component_id,
                orders.version,
                member,
                source_component_id=tests.component_id,
                source_expected_version=5,
            )
        )
    with pytest.raises(ProjectInputError):
        assign.execute(
            AssignComponentRequest(
                "prj_oie",
                orders.component_id,
                orders.version,
                ComponentMember(SourceScope("gh-1", "repo", "acme/unknown"), ""),
            )
        )


def test_operator_assignment_is_preserved_on_confirm(
    store: InMemoryProjectStore,
) -> None:
    _associate(store, TESTS)
    tests = _component_for(store, TESTS)
    _suggest(store, E2E)
    AssignComponent(store=store).execute(
        AssignComponentRequest(
            "prj_oie", tests.component_id, tests.version, ComponentMember(E2E, "")
        )
    )

    _confirm(store, E2E)

    (component,) = _components(store)
    assert component.members == (ComponentMember(TESTS, ""), ComponentMember(E2E, ""))
    (resolution,) = _resolve(store, "acme/oie-e2e:e2e/cancel.spec.ts")[
        "acme/oie-e2e:e2e/cancel.spec.ts"
    ]
    assert resolution.component_ids == (component.component_id,)


def test_unconfirmed_member_never_resolves(store: InMemoryProjectStore) -> None:
    _associate(store, TESTS)
    tests = _component_for(store, TESTS)
    _suggest(store, E2E)
    AssignComponent(store=store).execute(
        AssignComponentRequest(
            "prj_oie", tests.component_id, tests.version, ComponentMember(E2E, "")
        )
    )

    assert _resolve(store, "acme/oie-e2e:a.ts")["acme/oie-e2e:a.ts"] == ()
