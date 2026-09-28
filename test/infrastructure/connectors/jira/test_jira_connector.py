"""Jira KnowledgeConnector tests over a fake Jira client; no live requests."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import pytest

from domain.errors import ConnectorError, ConnectorUnavailableError
from domain.knowledge import SourceReference, SourceType
from infrastructure.connectors.jira.client import JiraIssuePage
from infrastructure.connectors.jira.connector import JiraKnowledgeConnector
from infrastructure.connectors.jira.errors import (
    JiraIssueLimitExceededError,
    JiraPaginationError,
)
from infrastructure.connectors.jira.issue_documents import JiraIssueConfig
from infrastructure.connectors.jira.site import JiraSite

CLOUD_ID = "11223344-a1b2-3b33-c444-def123456789"
SITE = JiraSite(
    cloud_id=CLOUD_ID, site_url="https://acme.atlassian.net", name="Acme"
)


class FakeJiraClient:
    """Serve scripted search pages keyed by (jql, next_page_token)."""

    def __init__(self, pages: Mapping[str, Sequence[JiraIssuePage]]) -> None:
        self._pages = {project: list(project_pages) for project, project_pages in pages.items()}
        self.search_calls: list[tuple[str, str | None]] = []
        self.requested_fields: list[tuple[str, ...]] = []

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage:
        self.search_calls.append((jql, next_page_token))
        self.requested_fields.append(tuple(fields))
        if len(self.search_calls) > 100:
            raise AssertionError("pagination did not terminate")
        project = jql.split('"')[1]
        pages = self._pages[project]
        index = sum(1 for call_jql, _ in self.search_calls if call_jql == jql) - 1
        return pages[min(index, len(pages) - 1)]


def _issue(key: str, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "summary": f"Summary of {key}",
        "updated": "2026-09-01T10:00:00.000+0000",
        "created": "2026-08-01T09:00:00.000+0000",
    }
    base.update(fields)
    return {"id": key.replace("-", ""), "key": key, "fields": base}


def _page(*issues: dict[str, object], token: str | None = None) -> JiraIssuePage:
    return JiraIssuePage(issues=issues, next_page_token=token, is_last=token is None)


def _connector(
    client: FakeJiraClient,
    *,
    projects: Sequence[str] = ("KAN",),
    include_comments: bool = False,
    page_size: int = 50,
    max_issues: int = 5000,
) -> JiraKnowledgeConnector:
    return JiraKnowledgeConnector(
        client,
        JiraIssueConfig(
            site=SITE,
            project_keys=tuple(projects),
            connector_id="conn-1",
            include_comments=include_comments,
            page_size=page_size,
            max_issues=max_issues,
        ),
    )


def test_lists_selected_project_issues_with_stable_identity_and_revision() -> None:
    client = FakeJiraClient(
        {"KAN": [_page(_issue("KAN-1"), _issue("KAN-2", updated="2026-09-02T00:00:00.000+0000"))]}
    )

    documents = _connector(client).list_documents()

    assert [d.reference for d in documents] == [
        SourceReference(f"{CLOUD_ID}/KAN:KAN-1", SourceType.JIRA),
        SourceReference(f"{CLOUD_ID}/KAN:KAN-2", SourceType.JIRA),
    ]
    assert [d.revision for d in documents] == [
        "2026-09-01T10:00:00.000+0000",
        "2026-09-02T00:00:00.000+0000",
    ]
    first = documents[0]
    assert first.file_name == "KAN-1.md"
    assert first.extra == {
        "connector_id": "conn-1",
        "cloud_id": CLOUD_ID,
        "jira_instance_id": CLOUD_ID,
        "project_key": "KAN",
        "issue_key": "KAN-1",
        "url": "https://acme.atlassian.net/browse/KAN-1",
    }
    assert client.search_calls == [('project = "KAN" ORDER BY key ASC', None)]


def test_lists_multiple_projects_in_selection_order() -> None:
    client = FakeJiraClient(
        {
            "OPS": [_page(_issue("OPS-7"))],
            "KAN": [_page(_issue("KAN-1"))],
        }
    )

    documents = _connector(client, projects=("OPS", "KAN")).list_documents()

    assert [d.source_id for d in documents] == [
        f"{CLOUD_ID}/OPS:OPS-7",
        f"{CLOUD_ID}/KAN:KAN-1",
    ]


def test_follows_next_page_token_until_last_page() -> None:
    client = FakeJiraClient(
        {
            "KAN": [
                _page(_issue("KAN-1"), _issue("KAN-2"), token="t1"),
                _page(_issue("KAN-3"), token="t2"),
                _page(_issue("KAN-4")),
            ]
        }
    )

    documents = _connector(client, page_size=2).list_documents()

    assert [d.extra["issue_key"] for d in documents] == ["KAN-1", "KAN-2", "KAN-3", "KAN-4"]
    assert [token for _, token in client.search_calls] == [None, "t1", "t2"]


def test_listing_beyond_max_issues_raises_and_stops_fetching() -> None:
    client = FakeJiraClient(
        {
            "KAN": [
                _page(_issue("KAN-1"), _issue("KAN-2"), token="t1"),
                _page(_issue("KAN-3"), _issue("KAN-4"), token="t2"),
                _page(_issue("KAN-5"), _issue("KAN-6"), token="t3"),
            ]
        }
    )

    with pytest.raises(JiraIssueLimitExceededError) as caught:
        _connector(client, page_size=2, max_issues=3).list_documents()

    assert isinstance(caught.value, ConnectorUnavailableError)
    assert len(client.search_calls) == 2


def test_listing_exactly_max_issues_succeeds() -> None:
    client = FakeJiraClient(
        {"KAN": [_page(_issue("KAN-1"), _issue("KAN-2"), token="t1"), _page(_issue("KAN-3"))]}
    )

    documents = _connector(client, page_size=2, max_issues=3).list_documents()

    assert len(documents) == 3


ADF_DESCRIPTION = {
    "type": "doc",
    "version": 1,
    "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Context"}]},
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Checkout "},
                {"type": "text", "text": "fails", "marks": [{"type": "strong"}]},
                {"type": "text", "text": " for "},
                {"type": "mention", "attrs": {"text": "@Mia"}},
            ],
        },
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "cart empty"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "card declined"}]}]},
            ],
        },
        {"type": "codeBlock", "attrs": {"language": "json"}, "content": [{"type": "text", "text": '{"a": 1}'}]},
    ],
}


def _rich_issue() -> dict[str, object]:
    return _issue(
        "KAN-9",
        summary="Checkout fails",
        description=ADF_DESCRIPTION,
        status={"name": "In Progress"},
        issuetype={"name": "Bug", "subtask": False},
        priority={"name": "High"},
        labels=["payments", "web"],
        assignee={"displayName": "Mia Krystof"},
        reporter={"displayName": "Sam Lee"},
        components=[{"name": "Checkout"}],
        fixVersions=[{"name": "2026.10"}],
        comment={
            "comments": [
                {
                    "author": {"displayName": "Ola"},
                    "created": "2026-09-01T11:00:00.000+0000",
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Reproduced on staging."}]}],
                    },
                }
            ]
        },
    )


def test_fetch_renders_issue_markdown_with_provenance() -> None:
    client = FakeJiraClient({"KAN": [_page(_rich_issue())]})
    connector = _connector(client)
    [document] = connector.list_documents()

    source = connector.fetch_document(document)

    assert source.reference == document.reference
    assert source.metadata.title == "KAN-9: Checkout fails"
    assert source.metadata.provider == "jira"
    assert source.metadata.content_format == "markdown"
    assert source.metadata.extra == {
        "file_name": "KAN-9.md",
        "connector_id": "conn-1",
        "jira_issue_key": "KAN-9",
        "jira_issue_url": "https://acme.atlassian.net/browse/KAN-9",
        "jira_instance_id": CLOUD_ID,
        "jira_project_key": "KAN",
        "jira_site_url": "https://acme.atlassian.net",
        "jira_updated_at": "2026-09-01T10:00:00.000+0000",
    }
    assert source.content == "\n".join(
        [
            "# KAN-9: Checkout fails",
            "",
            "- Key: KAN-9",
            "- Project: KAN",
            "- Type: Bug",
            "- Status: In Progress",
            "- Priority: High",
            "- Labels: payments, web",
            "- Assignee: Mia Krystof",
            "- Reporter: Sam Lee",
            "- Components: Checkout",
            "- Fix versions: 2026.10",
            "- URL: https://acme.atlassian.net/browse/KAN-9",
            "- Created: 2026-08-01T09:00:00.000+0000",
            "- Updated: 2026-09-01T10:00:00.000+0000",
            "",
            "## Description",
            "",
            "## Context",
            "",
            "Checkout **fails** for @Mia",
            "",
            "- cart empty",
            "- card declined",
            "",
            "```json",
            '{"a": 1}',
            "```",
        ]
    )


def test_comments_are_included_only_when_configured() -> None:
    client = FakeJiraClient({"KAN": [_page(_rich_issue())]})
    connector = _connector(client, include_comments=True)
    [document] = connector.list_documents()

    content = connector.fetch_document(document).content

    assert "comment" in client.requested_fields[0]
    assert content.endswith(
        "\n".join(
            [
                "## Comments",
                "",
                "### Comment by Ola",
                "",
                "- Created: 2026-09-01T11:00:00.000+0000",
                "",
                "Reproduced on staging.",
            ]
        )
    )


def _shouting_renderer(raw: object) -> str:
    return raw.upper() if isinstance(raw, str) else ""


def test_configured_renderer_renders_description_and_comment_bodies() -> None:
    issue = _issue(
        "KAN-5",
        description="broken *checkout*",
        comment={
            "comments": [
                {
                    "author": {"displayName": "Ola"},
                    "created": "2026-09-01T11:00:00.000+0000",
                    "body": "seen on _staging_",
                }
            ]
        },
    )
    client = FakeJiraClient({"KAN": [_page(issue)]})
    connector = JiraKnowledgeConnector(
        client,
        JiraIssueConfig(
            site=SITE,
            project_keys=("KAN",),
            include_comments=True,
            render_text=_shouting_renderer,
        ),
    )
    [document] = connector.list_documents()

    content = connector.fetch_document(document).content

    assert "## Description\n\nBROKEN *CHECKOUT*" in content
    assert content.endswith("- Created: 2026-09-01T11:00:00.000+0000\n\nSEEN ON _STAGING_")


def test_default_renderer_reads_atlassian_document_format_comments() -> None:
    client = FakeJiraClient({"KAN": [_page(_rich_issue())]})
    connector = JiraKnowledgeConnector(
        client,
        JiraIssueConfig(site=SITE, project_keys=("KAN",), include_comments=True),
    )
    [document] = connector.list_documents()

    content = connector.fetch_document(document).content

    assert "Checkout **fails** for @Mia" in content
    assert content.endswith("Reproduced on staging.")


def test_comments_are_excluded_by_default() -> None:
    client = FakeJiraClient({"KAN": [_page(_rich_issue())]})
    connector = _connector(client)
    [document] = connector.list_documents()

    content = connector.fetch_document(document).content

    assert "comment" not in client.requested_fields[0]
    assert "Reproduced on staging." not in content


def test_subtasks_are_ingested_as_issues_with_parent() -> None:
    subtask = _issue(
        "KAN-10",
        issuetype={"name": "Sub-task", "subtask": True},
        parent={"key": "KAN-9"},
    )
    client = FakeJiraClient({"KAN": [_page(_issue("KAN-9"), subtask)]})
    connector = _connector(client)

    documents = connector.list_documents()
    content = connector.fetch_document(documents[1]).content

    assert [d.extra["issue_key"] for d in documents] == ["KAN-9", "KAN-10"]
    assert "- Type: Sub-task\n- Parent: KAN-9\n" in content


def test_fetch_of_unlisted_issue_fails_per_document() -> None:
    client = FakeJiraClient({"KAN": [_page(_issue("KAN-1"))]})
    connector = _connector(client)
    [document] = connector.list_documents()
    missing = dataclasses.replace(
        document, reference=SourceReference(f"{CLOUD_ID}/KAN:KAN-404", SourceType.JIRA)
    )

    with pytest.raises(ConnectorError) as caught:
        connector.fetch_document(missing)

    assert not isinstance(caught.value, ConnectorUnavailableError)


def test_listing_requests_only_the_mapped_fields() -> None:
    client = FakeJiraClient({"KAN": [_page(_issue("KAN-1"))]})

    _connector(client).list_documents()

    assert set(client.requested_fields[0]) == {
        "summary",
        "description",
        "status",
        "issuetype",
        "priority",
        "labels",
        "assignee",
        "reporter",
        "components",
        "fixVersions",
        "parent",
        "created",
        "updated",
    }


def test_issue_repeated_across_pages_is_listed_once() -> None:
    client = FakeJiraClient(
        {"KAN": [_page(_issue("KAN-1"), _issue("KAN-2"), token="t1"), _page(_issue("KAN-2"))]}
    )

    documents = _connector(client).list_documents()

    assert [d.extra["issue_key"] for d in documents] == ["KAN-1", "KAN-2"]


def test_repeated_next_page_token_fails_safely() -> None:
    client = FakeJiraClient(
        {
            "KAN": [
                _page(_issue("KAN-1"), token="same"),
                _page(_issue("KAN-2"), token="same"),
            ]
        }
    )

    with pytest.raises(JiraPaginationError):
        _connector(client).list_documents()

    assert len(client.search_calls) == 2


class EndlessEmptyPagesClient:
    """Return empty non-last pages with a fresh token forever."""

    def __init__(self) -> None:
        self.calls = 0

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage:
        self.calls += 1
        if self.calls > 1000:
            raise AssertionError("pagination did not terminate")
        return JiraIssuePage(issues=(), next_page_token=f"t{self.calls}", is_last=False)


def test_endless_fresh_tokens_stop_at_page_bound() -> None:
    client = EndlessEmptyPagesClient()
    connector = JiraKnowledgeConnector(
        client,
        JiraIssueConfig(site=SITE, project_keys=("KAN",), page_size=10, max_issues=30),
    )

    with pytest.raises(JiraPaginationError):
        connector.list_documents()

    assert client.calls == 4


@pytest.mark.parametrize(
    "page",
    [
        JiraIssuePage(issues=(), next_page_token=None, is_last=False),
        JiraIssuePage(issues=(), next_page_token="  ", is_last=False),
        JiraIssuePage(issues="not-a-list", next_page_token=None, is_last=True),  # type: ignore[arg-type]
    ],
)
def test_malformed_page_raises_instead_of_returning_partial_list(page: JiraIssuePage) -> None:
    client = FakeJiraClient({"KAN": [page]})

    with pytest.raises(JiraPaginationError):
        _connector(client).list_documents()


SERVER_ID = "B8E7-4C2A-9F31-0D6E"
DC_SITE = JiraSite(
    cloud_id=SERVER_ID, site_url="https://jira.example.com/jira", name="Example Jira"
)


def test_data_center_documents_use_the_server_id_without_cloud_metadata() -> None:
    client = FakeJiraClient({"KAN": [_page(_issue("KAN-1"))]})
    connector = JiraKnowledgeConnector(
        client,
        JiraIssueConfig(
            site=DC_SITE,
            project_keys=("KAN",),
            connector_id="conn-dc",
            deployment="data_center",
        ),
    )

    [document] = connector.list_documents()
    source = connector.fetch_document(document)

    assert document.source_id == f"{SERVER_ID}/KAN:KAN-1"
    assert document.extra == {
        "connector_id": "conn-dc",
        "jira_instance_id": SERVER_ID,
        "project_key": "KAN",
        "issue_key": "KAN-1",
        "url": "https://jira.example.com/jira/browse/KAN-1",
    }
    assert "cloud_id" not in source.metadata.extra
    assert source.metadata.extra["jira_instance_id"] == SERVER_ID
    assert source.metadata.extra["jira_issue_url"] == "https://jira.example.com/jira/browse/KAN-1"
    assert "- URL: https://jira.example.com/jira/browse/KAN-1" in source.content


def _counted_page(
    *issues: dict[str, object], total: int, token: str | None = None
) -> JiraIssuePage:
    return JiraIssuePage(
        issues=issues, next_page_token=token, is_last=token is None, total=total
    )


def test_total_that_changes_between_pages_aborts_the_listing() -> None:
    client = FakeJiraClient(
        {
            "KAN": [
                _counted_page(_issue("KAN-1"), _issue("KAN-2"), total=100, token="2"),
                _counted_page(_issue("KAN-3"), _issue("KAN-4"), total=90, token="4"),
            ]
        }
    )

    with pytest.raises(JiraPaginationError):
        _connector(client, page_size=2).list_documents()

    assert len(client.search_calls) == 2


def test_consistent_totals_paginate_per_project() -> None:
    client = FakeJiraClient(
        {
            "KAN": [
                _counted_page(_issue("KAN-1"), total=2, token="1"),
                _counted_page(_issue("KAN-2"), total=2),
            ],
            "OPS": [_counted_page(_issue("OPS-1"), total=1)],
        }
    )

    documents = _connector(client, projects=("KAN", "OPS"), page_size=1).list_documents()

    assert [d.extra["issue_key"] for d in documents] == ["KAN-1", "KAN-2", "OPS-1"]
