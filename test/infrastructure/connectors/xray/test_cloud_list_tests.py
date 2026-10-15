"""Xray Cloud ``list_tests`` and ``story_naming_context`` (#400)."""

from __future__ import annotations

import json

import httpx
import pytest

from domain.errors import ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import JiraIssueSummary, StoryNamingContext
from infrastructure.connectors.xray.cloud import XrayCloudImporter
from infrastructure.connectors.xray.schema import XraySchemaCache
from test.infrastructure.connectors.xray.test_cloud_importer import BASE_URL, CLIENT_SECRET, TOKEN


def _jira(
    key: str,
    summary: str = "Login",
    *,
    type_id: str = "10002",
    type_name: str = "Test",
    parent: object | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "key": key,
        "summary": summary,
        "issuetype": {"id": type_id, "name": type_name},
    }
    if parent is not None:
        body["parent"] = parent
    return {"jira": body}


class _ListSearch:
    def __init__(self, tests=(), coverable=(), *, page: int = 100) -> None:
        self.tests = list(tests)
        self.coverable = list(coverable)
        self.page = page
        self.queries: list[dict[str, object]] = []
        self.repeat_page = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        body = json.loads(request.content)
        self.queries.append(body)
        name = "getTests" if "getTests" in body["query"] else "getCoverableIssues"
        items = self.tests if name == "getTests" else self.coverable
        jql = body["variables"]["jql"]
        if "project =" in jql and "component =" in jql:
            # component filter is applied by Jira; tests here are pre-filtered by the suite
            pass
        start = body["variables"]["start"]
        if self.repeat_page and start > 0:
            page = items[: self.page]
        else:
            page = items[start : start + self.page]
        return httpx.Response(
            200,
            json={"data": {name: {"total": len(items), "start": start, "results": page}}},
        )


def _importer(handler) -> XrayCloudImporter:
    return XrayCloudImporter(
        base_url=BASE_URL,
        client_id="id",
        client_secret=CLIENT_SECRET,
        project_key="QA",
        link_type="Test",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(handler),
    )


def test_list_tests_pages_and_dedupes_by_key() -> None:
    xray = _ListSearch(
        tests=[_jira(f"QA-{n}") for n in range(1, 6)],
        page=2,
    )

    listed = _importer(xray).list_tests("QA")

    assert [t.key for t in listed] == [f"QA-{n}" for n in range(1, 6)]
    assert all(isinstance(t, JiraIssueSummary) and t.is_test for t in listed)
    assert [q["variables"]["start"] for q in xray.queries] == [0, 2, 4]
    assert all('project = "QA"' in q["variables"]["jql"] for q in xray.queries)


def test_list_tests_includes_component_in_jql() -> None:
    xray = _ListSearch(tests=[_jira("QA-1")])

    _importer(xray).list_tests("QA", component="Portal")

    assert 'component = "Portal"' in xray.queries[0]["variables"]["jql"]


def test_list_tests_escapes_quotes_in_component() -> None:
    xray = _ListSearch(tests=[_jira("QA-1")])

    _importer(xray).list_tests("QA", component='Portal" OR project = "OTHER\\')

    assert xray.queries[0]["variables"]["jql"] == (
        'project = "QA" AND component = "Portal\\" OR project = \\"OTHER\\\\"'
    )


def test_list_tests_rejects_non_advancing_duplicate_page() -> None:
    xray = _ListSearch(tests=[_jira(f"QA-{n}") for n in range(1, 5)], page=2)
    xray.repeat_page = True

    with pytest.raises(ConnectorUnavailableError):
        _importer(xray).list_tests("QA")


def test_story_naming_context_absent_present_and_failed() -> None:
    absent = _ListSearch(coverable=[_jira("ABC-1", "As a user", type_id="1", type_name="Story")])
    assert _importer(absent).story_naming_context("ABC-1") == StoryNamingContext(
        "ABC-1", "As a user", "absent"
    )

    present = _ListSearch(
        coverable=[
            _jira(
                "ABC-1",
                "As a user",
                type_id="1",
                type_name="Story",
                parent={"key": "EPIC-1", "fields": {"summary": "Checkout"}},
            )
        ]
    )
    assert _importer(present).story_naming_context("ABC-1") == StoryNamingContext(
        "ABC-1",
        "As a user",
        "present",
        epic_key="EPIC-1",
        epic_summary="Checkout",
    )

    failed = _ListSearch(
        coverable=[
            _jira(
                "ABC-1",
                "As a user",
                type_id="1",
                type_name="Story",
                parent={"key": "EPIC-1"},
            )
        ]
    )
    assert _importer(failed).story_naming_context("ABC-1").epic_presence == "failed"


def test_story_naming_context_requires_exactly_one_coverable_row() -> None:
    xray = _ListSearch(coverable=[])
    with pytest.raises(ConnectorError):
        _importer(xray).story_naming_context("ABC-1")
