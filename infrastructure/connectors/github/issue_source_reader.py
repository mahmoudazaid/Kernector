"""Live GitHub Issue → SourceDocument adapter (REST Get Issue)."""

from __future__ import annotations

from collections.abc import Mapping

from domain.errors import ConnectorError
from domain.knowledge import (
    SourceDocument,
    SourceLocator,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.connectors.github.client import GitHubClient
from infrastructure.connectors.github.issue_locator import (
    InvalidGitHubIssueLocatorError,
    ParsedGitHubIssueLocator,
    parse_github_issue_locator,
)

_MSG_REQUEST_FAILED = "The GitHub request failed."
_MSG_EMPTY_BODY = "GitHub Issue body is empty."
_MSG_NOT_ISSUE = "GitHub Pull Requests cannot be used as Test Design sources."
_MSG_LOCATOR_MISMATCH = "GitHub Issue response did not match the requested locator."
_MSG_UNSUPPORTED_PROVIDER = "Live source provider is not supported."

ISSUE_SOURCE_ID_PREFIX = "issue:"


class GitHubIssueEmptyBodyError(ConnectorError):
    """Issue exists but has no body text usable as planning evidence."""


class GitHubIssueSourceReader:
    """``LiveSourceReader`` for a single GitHub Issue via REST."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        if locator.provider.strip().casefold() != "github":
            raise ConnectorError(_MSG_UNSUPPORTED_PROVIDER)
        try:
            parsed = parse_github_issue_locator(locator.locator)
        except Exception as error:  # pragma: no cover - parse returns None
            raise ConnectorError(_MSG_REQUEST_FAILED) from error
        if parsed is None:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        payload = self._client.get_issue(parsed.owner, parsed.repo, parsed.number)
        return issue_payload_to_source_document(payload, expected=parsed)


def issue_payload_to_source_document(
    payload: Mapping[str, object],
    *,
    expected: ParsedGitHubIssueLocator,
) -> SourceDocument:
    """Map a REST Issue payload to ``SourceDocument``.

    Rejects Pull Request payloads and blank bodies. Verifies number + repo
    match ``expected``.
    """
    if "pull_request" in payload:
        raise ConnectorError(_MSG_NOT_ISSUE)
    number = payload.get("number")
    if not isinstance(number, int) or number != expected.number:
        raise ConnectorError(_MSG_LOCATOR_MISMATCH)
    repo_full = _repository_full_name(payload)
    if repo_full is None or repo_full.casefold() != (
        f"{expected.owner}/{expected.repo}".casefold()
    ):
        raise ConnectorError(_MSG_LOCATOR_MISMATCH)
    node_id = payload.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    updated_at = payload.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    body = payload.get("body")
    if body is None or (isinstance(body, str) and not body.strip()):
        raise GitHubIssueEmptyBodyError(_MSG_EMPTY_BODY)
    if not isinstance(body, str):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    html_url = payload.get("html_url")
    issue_url = (
        html_url.strip()
        if isinstance(html_url, str) and html_url.strip()
        else f"https://github.com/{expected.owner}/{expected.repo}/issues/{expected.number}"
    )
    content = _markdown_for_issue(
        title=title.strip(),
        body=body.strip(),
        state=_optional_text(payload.get("state")) or "unknown",
        repository=repo_full,
        url=issue_url,
        updated_at=updated_at.strip(),
    )
    source_id = f"{ISSUE_SOURCE_ID_PREFIX}{node_id.strip()}"
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(source_id, SourceType.GITHUB),
            title=title.strip(),
            provider="github",
            content_format="markdown",
            extra={
                "github_kind": "issue",
                "github_issue_id": source_id,
                "github_issue_number": str(expected.number),
                "github_issue_url": issue_url,
                "github_repository": repo_full,
                "github_updated_at": updated_at.strip(),
                "revision": updated_at.strip(),
            },
        ),
        content,
    )


def _repository_full_name(payload: Mapping[str, object]) -> str | None:
    repository = payload.get("repository")
    if isinstance(repository, Mapping):
        full_name = repository.get("full_name")
        if isinstance(full_name, str) and full_name.strip():
            return full_name.strip()
    html_url = payload.get("html_url")
    if isinstance(html_url, str):
        try:
            parsed = parse_github_issue_locator(html_url.strip())
        except InvalidGitHubIssueLocatorError:
            parsed = None
        if parsed is not None:
            return f"{parsed.owner}/{parsed.repo}"
    repository_url = payload.get("repository_url")
    if isinstance(repository_url, str) and "/repos/" in repository_url:
        tail = repository_url.rstrip("/").split("/repos/", 1)[-1]
        parts = tail.split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return f"{parts[0]}/{parts[1]}"
    return None


def _markdown_for_issue(
    *,
    title: str,
    body: str,
    state: str,
    repository: str,
    url: str,
    updated_at: str,
) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- State: {state}",
            f"- Repository: {repository}",
            f"- URL: {url}",
            f"- Updated: {updated_at}",
            "",
            "## Body",
            "",
            body,
        ]
    )


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
