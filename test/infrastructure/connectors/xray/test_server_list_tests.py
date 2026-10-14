"""Xray Server ``list_tests`` and ``story_naming_context`` (#400)."""

from __future__ import annotations

import httpx
import pytest

from domain.errors import ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import JiraIssueSummary, StoryNamingContext
from infrastructure.connectors.xray.schema import XraySchemaCache
from infrastructure.connectors.xray.server import XrayServerImporter
from test.infrastructure.connectors.xray.test_server_schema import (
    API,
    BASE_URL,
    TOKEN,
    xray_fields,
)


def _issue(key: str, summary: str, type_id: str = "10100", type_name: str = "Test", **fields):
    return {
        "key": key,
        "fields": {"summary": summary, "issuetype": {"id": type_id, "name": type_name}, **fields},
    }


class _SearchJira:
    def __init__(
        self,
        *,
        issues: list[dict] | None = None,
        story: dict | None = None,
        epic: dict | None = None,
        fields_meta: list | None = None,
        page: int = 100,
        repeat_page: bool = False,
    ) -> None:
        self.issues = list(issues or [])
        self.story = story
        self.epic = epic
        self.fields_meta = fields_meta if fields_meta is not None else [
            {"id": "customfield_10014", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-epic-link"}}
        ]
        self.page = page
        self.repeat_page = repeat_page
        self.search_starts: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{API}/issue/createmeta/QA/issuetypes":
            return httpx.Response(200, json={"values": [{"id": "10100", "name": "Test"}]})
        if path == f"{API}/issue/createmeta/QA/issuetypes/10100":
            return httpx.Response(200, json={"values": xray_fields(), "isLast": True})
        if path == f"{API}/field":
            return httpx.Response(200, json=self.fields_meta)
        if path == f"{API}/search":
            start = int(request.url.params["startAt"])
            self.search_starts.append(start)
            if self.repeat_page and start > 0:
                page = self.issues[: self.page]
            else:
                page = self.issues[start : start + self.page]
            return httpx.Response(
                200, json={"issues": page, "total": len(self.issues), "startAt": start}
            )
        if path.startswith(f"{API}/issue/"):
            key = path.rsplit("/", 1)[-1]
            if self.story is not None and key == self.story["key"]:
                return httpx.Response(200, json=self.story)
            if self.epic is not None and key == self.epic["key"]:
                return httpx.Response(200, json=self.epic)
            return httpx.Response(404)
        return httpx.Response(500)


def _importer(handler) -> XrayServerImporter:
    return XrayServerImporter(
        base_url=BASE_URL,
        token=TOKEN,
        project_key="QA",
        link_type="Test",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(handler),
    )


def test_list_tests_pages_and_includes_component_filter() -> None:
    jira = _SearchJira(
        issues=[_issue(f"QA-{n}", "T") for n in range(1, 5)],
        page=2,
    )

    listed = _importer(jira).list_tests("QA", component="Portal")

    assert [t.key for t in listed] == [f"QA-{n}" for n in range(1, 5)]
    assert all(isinstance(t, JiraIssueSummary) and t.is_test for t in listed)
    assert jira.search_starts == [0, 2]


def test_list_tests_rejects_duplicate_keys_across_pages() -> None:
    jira = _SearchJira(issues=[_issue(f"QA-{n}", "T") for n in range(1, 4)], page=2, repeat_page=True)

    with pytest.raises(ConnectorUnavailableError):
        _importer(jira).list_tests("QA")


def test_story_naming_context_parent_present() -> None:
    story = _issue(
        "ABC-1",
        "As a user",
        "10001",
        "Story",
        parent={"key": "EPIC-1", "fields": {"summary": "Checkout"}},
    )
    jira = _SearchJira(story=story, fields_meta=[])

    assert _importer(jira).story_naming_context("ABC-1") == StoryNamingContext(
        "ABC-1",
        "As a user",
        "present",
        epic_key="EPIC-1",
        epic_summary="Checkout",
    )


def test_story_naming_context_resolves_epic_link_key() -> None:
    story = _issue(
        "ABC-1",
        "As a user",
        "10001",
        "Story",
        customfield_10014="EPIC-1",
    )
    epic = _issue("EPIC-1", "Checkout", "10000", "Epic")
    jira = _SearchJira(story=story, epic=epic)

    assert _importer(jira).story_naming_context("ABC-1") == StoryNamingContext(
        "ABC-1",
        "As a user",
        "present",
        epic_key="EPIC-1",
        epic_summary="Checkout",
    )


def test_story_naming_context_absent_when_no_epic() -> None:
    story = _issue("ABC-1", "As a user", "10001", "Story")
    jira = _SearchJira(story=story, fields_meta=[])

    assert _importer(jira).story_naming_context("ABC-1") == StoryNamingContext(
        "ABC-1", "As a user", "absent"
    )


def test_story_naming_context_failed_when_epic_missing() -> None:
    story = _issue(
        "ABC-1",
        "As a user",
        "10001",
        "Story",
        customfield_10014="EPIC-404",
    )
    jira = _SearchJira(story=story)

    assert _importer(jira).story_naming_context("ABC-1").epic_presence == "failed"
