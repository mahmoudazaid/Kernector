"""Authoritative GitHub Issue locator parsing (URL and owner/repo#N)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_OWNER_REPO = r"(?P<owner>[A-Za-z0-9_.-]{1,39})/(?P<repo>[A-Za-z0-9_.-]{1,100})"
_URL_PATTERN = re.compile(
    rf"https?://(?:www\.)?github\.com/{_OWNER_REPO}/issues/(?P<number>\d+)(?![\w/])",
    re.IGNORECASE,
)
_HASH_PATTERN = re.compile(rf"\b{_OWNER_REPO}#(?P<number>\d+)\b")
# Slash form (owner/repo/N). Negative lookbehind avoids matching .../issues/N URLs
# already covered by _URL_PATTERN; negative lookahead skips /pull/ and similar.
_SLASH_PATTERN = re.compile(
    rf"(?<![\w./]){_OWNER_REPO}/(?P<number>\d+)\b(?!/)",
)


class InvalidGitHubIssueLocatorError(ValueError):
    """Locator string is not a single well-formed GitHub Issue reference."""


class AmbiguousGitHubIssueLocatorError(ValueError):
    """Text contains more than one distinct GitHub Issue reference."""


@dataclass(frozen=True, slots=True)
class ParsedGitHubIssueLocator:
    """One canonical GitHub Issue identity."""

    owner: str
    repo: str
    number: int

    @property
    def canonical(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.owner.casefold(), self.repo.casefold(), self.number)


def parse_github_issue_locator(text: str) -> ParsedGitHubIssueLocator | None:
    """Parse a standalone locator (URL or owner/repo#N). Returns None if invalid."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or stripped.isdigit():
        return None
    match = (
        _URL_PATTERN.fullmatch(stripped)
        or _HASH_PATTERN.fullmatch(stripped)
        or _SLASH_PATTERN.fullmatch(stripped)
    )
    if match is None:
        # Allow optional trailing punctuation stripped by callers; try patterns
        # that match the whole string only.
        return None
    try:
        return _from_match(match)
    except InvalidGitHubIssueLocatorError:
        return None


def canonicalize_github_issue_locator(text: str) -> str:
    """Return canonical owner/repo#N or raise InvalidGitHubIssueLocatorError."""
    parsed = parse_github_issue_locator(text)
    if parsed is None:
        raise InvalidGitHubIssueLocatorError(
            "GitHub Issue locator must be a full issue URL or owner/repo#number"
        )
    return parsed.canonical


def extract_github_issue_locator(text: str) -> ParsedGitHubIssueLocator | None:
    """Extract exactly one Issue from free text.

    Duplicate mentions of the same Issue are accepted. Multiple distinct Issues
    raise AmbiguousGitHubIssueLocatorError. Returns None when none are found.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    found: list[ParsedGitHubIssueLocator] = []
    for pattern in (_URL_PATTERN, _HASH_PATTERN, _SLASH_PATTERN):
        for match in pattern.finditer(text):
            try:
                found.append(_from_match(match))
            except InvalidGitHubIssueLocatorError:
                continue
    if not found:
        return None
    unique: dict[tuple[str, str, int], ParsedGitHubIssueLocator] = {}
    for item in found:
        unique.setdefault(item.key, item)
    if len(unique) > 1:
        raise AmbiguousGitHubIssueLocatorError(
            "Query must reference exactly one GitHub Issue"
        )
    return next(iter(unique.values()))


def _from_match(match: re.Match[str]) -> ParsedGitHubIssueLocator:
    number = int(match.group("number"))
    owner = match.group("owner")
    repo = match.group("repo")
    if number < 1 or not _valid_segment(owner) or not _valid_segment(repo):
        raise InvalidGitHubIssueLocatorError(
            "GitHub Issue locator must use a valid owner, repo, and number"
        )
    return ParsedGitHubIssueLocator(
        owner=owner,
        repo=repo,
        number=number,
    )


def _valid_segment(value: str) -> bool:
    return bool(value.strip()) and value.strip(".") != ""
