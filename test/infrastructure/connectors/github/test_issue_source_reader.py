"""Tests for REST Issue → SourceDocument mapping and live reader."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from domain.errors import ConnectorError
from domain.knowledge import SourceLocator
from infrastructure.connectors.github.issue_locator import parse_github_issue_locator
from infrastructure.connectors.github.issue_source_reader import (
    GitHubIssueEmptyBodyError,
    GitHubIssueLocatorMismatchError,
    GitHubIssueNotIssueError,
    GitHubIssueSourceReader,
    issue_payload_to_source_document,
)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "node_id": "I_kwDOExample",
        "number": 293,
        "title": "Live fetch",
        "body": "Acceptance criteria live here.",
        "state": "open",
        "labels": [{"name": "bug"}, {"name": "P1"}],
        "assignees": [{"login": "ada"}, {"login": "grace"}],
        "milestone": {"title": "MVP"},
        "created_at": "2026-09-13T12:00:00Z",
        "closed_at": None,
        "html_url": "https://github.com/mahmoudazaid/Kernector/issues/293",
        "updated_at": "2026-09-14T12:00:00Z",
        "repository_url": "https://api.github.com/repos/mahmoudazaid/Kernector",
        "repository": {"full_name": "mahmoudazaid/Kernector"},
    }
    base.update(overrides)
    return base


def test_maps_issue_payload_to_source_document() -> None:
    expected = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert expected is not None
    doc = issue_payload_to_source_document(_payload(), expected=expected)
    assert doc.source_id == "issue:I_kwDOExample"
    assert doc.reference.source_type == "github"
    assert "Acceptance criteria" in doc.content
    assert "Labels: bug, P1" in doc.content
    assert "Assignees: ada, grace" in doc.content
    assert "Milestone: MVP" in doc.content
    assert "Created: 2026-09-13T12:00:00Z" in doc.content
    assert "Closed: " not in doc.content
    assert doc.metadata.extra["github_issue_url"].endswith("/issues/293")
    assert doc.metadata.extra["github_issue_state"] == "open"
    assert doc.metadata.extra["github_labels"] == "bug,P1"
    assert doc.metadata.extra["github_assignees"] == "ada,grace"
    assert doc.metadata.extra["github_milestone"] == "MVP"
    assert doc.metadata.extra["github_created_at"] == "2026-09-13T12:00:00Z"
    assert doc.metadata.extra["github_closed_at"] == ""
    assert doc.metadata.extra["revision"] == "2026-09-14T12:00:00Z"


def test_rejects_pull_request_payload() -> None:
    expected = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert expected is not None
    with pytest.raises(GitHubIssueNotIssueError, match="Pull Request"):
        issue_payload_to_source_document(
            _payload(pull_request={"url": "https://api.github.com/..."}),
            expected=expected,
        )


def test_rejects_locator_mismatch() -> None:
    expected = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert expected is not None
    with pytest.raises(GitHubIssueLocatorMismatchError, match="did not match"):
        issue_payload_to_source_document(_payload(number=8), expected=expected)


def test_rejects_unrelated_html_url() -> None:
    expected = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert expected is not None
    with pytest.raises(GitHubIssueLocatorMismatchError, match="did not match"):
        issue_payload_to_source_document(
            _payload(html_url="https://github.com/other/repo/issues/293"),
            expected=expected,
        )


def test_constructs_canonical_url_when_html_url_missing() -> None:
    expected = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert expected is not None
    doc = issue_payload_to_source_document(_payload(html_url=None), expected=expected)

    assert (
        doc.metadata.extra["github_issue_url"]
        == "https://github.com/mahmoudazaid/Kernector/issues/293"
    )


@pytest.mark.parametrize("body", [None, "", "   "])
def test_blank_body_raises_empty_body_error(body: object) -> None:
    expected = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert expected is not None
    with pytest.raises(GitHubIssueEmptyBodyError):
        issue_payload_to_source_document(_payload(body=body), expected=expected)


def test_reader_fetch_uses_client() -> None:
    class _Client:
        def get_issue(
            self, owner: str, repo: str, issue_number: int
        ) -> Mapping[str, object]:
            assert (owner, repo, issue_number) == ("mahmoudazaid", "Kernector", 293)
            return _payload()

    reader = GitHubIssueSourceReader(_Client())  # type: ignore[arg-type]
    doc = reader.fetch(
        SourceLocator(provider="github", locator="mahmoudazaid/Kernector#293")
    )
    assert doc.source_id == "issue:I_kwDOExample"
