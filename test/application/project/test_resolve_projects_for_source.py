"""Resolve catalog documents to projects through connector scopes (#372).

Uses the real GitHub and Jira scope resolvers so the supported identity
formats are pinned at the use-case seam.
"""

from __future__ import annotations

import pytest

from application.project.resolve import ResolveProjectsForSource
from domain.knowledge import SourceReference
from domain.project.models import SourceScope
from infrastructure.connectors.github.project_scope import GitHubSourceScopeResolver
from infrastructure.connectors.jira.project_scope import JiraSourceScopeResolver
from test.application.project.project_fakes import (
    InMemoryProjectStore,
    catalog_document,
    confirmed,
)
from test.document_doubles import InMemoryDocumentCatalog

PROJ_JIRA = SourceScope("jira-1", "project_key", "PROJ")
PAY_JIRA = SourceScope("jira-1", "project_key", "PAY")
ORDERS = SourceScope("gh-1", "repo", "acme/proj-orders")
TESTS = SourceScope("gh-1", "repo", "acme/proj-tests")
LIB = SourceScope("gh-1", "repo", "acme/shared-lib")

DOCUMENTS = {
    "proj_story": ("cloud-abc/PROJ:PROJ-123", "jira", "jira-1"),
    "pay_story": ("cloud-abc/PAY:PAY-7", "jira", "jira-1"),
    "orders_file": ("acme/proj-orders:orders/cancel.py", "github", "gh-1"),
    "tests_file": ("acme/proj-tests:tests/test_cancel.py", "github", "gh-1"),
    "lib_file": ("acme/shared-lib:src/money.py", "github", "gh-1"),
    "colon_path": ("acme/proj-orders:orders/cancel:v2.py", "github", "gh-1"),
    "github_issue": ("issue:I_kwDOABC123", "github", "gh-1"),
    "dc_instance_with_slash": ("srv/eu-1/PROJ:PROJ-9", "jira", "jira-1"),
    "jira_bad_key": ("cloud-abc/proj:proj-1", "jira", "jira-1"),
    "jira_key_mismatch": ("cloud-abc/PROJ:PAY-1", "jira", "jira-1"),
    "jira_no_instance": ("PROJ:PROJ-1", "jira", "jira-1"),
    "jira_on_demand": ("issue:10001", "jira", "jira-1"),
    "drive_file": ("1AbCdEfG", "google_drive", "drive-1"),
    "no_connector": ("acme/proj-orders:orders/refund.py", "github", None),
    "upload": ("upload-1", "upload", None),
}


def _ref(name: str) -> SourceReference:
    source_id, source_type, _ = DOCUMENTS[name]
    return SourceReference(source_id, source_type)


@pytest.fixture
def store() -> InMemoryProjectStore:
    store = InMemoryProjectStore()
    with store.transaction() as tx:
        for association in (
            confirmed("prj_proj", PROJ_JIRA, ("business",)),
            confirmed("prj_proj", ORDERS, ("backend", "api_contract")),
            confirmed("prj_proj", TESTS, ("testing",)),
            confirmed("prj_proj", LIB),
            confirmed("prj_pay", PAY_JIRA, ("business",)),
            confirmed("prj_pay", LIB),
        ):
            tx.associations.add(association)
    return store


@pytest.fixture
def resolve(store: InMemoryProjectStore) -> ResolveProjectsForSource:
    catalog = InMemoryDocumentCatalog()
    for source_id, source_type, connector_id in DOCUMENTS.values():
        catalog.upsert(catalog_document(source_id, source_type, connector_id))
    return ResolveProjectsForSource(
        store=store,
        catalog=catalog,
        resolvers={
            "github": GitHubSourceScopeResolver(),
            "jira": JiraSourceScopeResolver(),
        },
    )


@pytest.mark.parametrize(
    "name,projects",
    [
        ("proj_story", ("prj_proj",)),
        ("orders_file", ("prj_proj",)),
        ("tests_file", ("prj_proj",)),
        ("pay_story", ("prj_pay",)),
        ("lib_file", ("prj_pay", "prj_proj")),
    ],
)
def test_documents_resolve_to_their_projects(
    resolve: ResolveProjectsForSource, name: str, projects: tuple[str, ...]
) -> None:
    assert resolve.execute(_ref(name)) == projects


def test_removed_association_is_excluded_immediately(
    store: InMemoryProjectStore, resolve: ResolveProjectsForSource
) -> None:
    with store.transaction() as tx:
        tx.associations.delete("prj_proj", ORDERS, expected_version=1)

    assert resolve.execute(_ref("orders_file")) == ()


def test_unknown_document_resolves_to_nothing(
    resolve: ResolveProjectsForSource,
) -> None:
    assert resolve.execute(SourceReference("acme/x:y", "github")) == ()


@pytest.mark.parametrize(
    "name,projects",
    [
        ("colon_path", ("prj_proj",)),
        ("dc_instance_with_slash", ("prj_proj",)),
        ("github_issue", ()),
        ("jira_bad_key", ()),
        ("jira_key_mismatch", ()),
        ("jira_no_instance", ()),
        ("jira_on_demand", ()),
        ("drive_file", ()),
        ("no_connector", ()),
        ("upload", ()),
    ],
)
def test_supported_identity_formats(
    resolve: ResolveProjectsForSource, name: str, projects: tuple[str, ...]
) -> None:
    assert resolve.execute(_ref(name)) == projects


def test_resolvers_expose_scope_and_path() -> None:
    github = GitHubSourceScopeResolver()
    jira = JiraSourceScopeResolver()
    orders = catalog_document("acme/proj-orders:orders/cancel:v2.py", "github", "gh-1")
    story = catalog_document("cloud-abc/PROJ:PROJ-123", "jira", "jira-1")

    assert github.scopes_for(orders) == (ORDERS,)
    assert github.path_for(orders) == "orders/cancel:v2.py"
    assert jira.scopes_for(story) == (PROJ_JIRA,)
    assert jira.path_for(story) is None
    assert github.scope_kinds == frozenset({"repo"})
    assert jira.scope_kinds == frozenset({"project_key"})
    assert github.component_forming_scope_kinds == frozenset({"repo"})
    assert jira.component_forming_scope_kinds == frozenset()
