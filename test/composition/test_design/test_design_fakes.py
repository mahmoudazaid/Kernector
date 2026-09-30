"""Offline Test Design doubles: live Issue reader, chat model, and facade builder."""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from composition.test_design.facade import TestDesignFacade
from composition.test_design.errors import TestDesignValidationError
from composition.test_design.github_source import GitHubTestDesignSource
from composition.test_design.sources import (
    AmbiguousSourceLocatorError,
    TestDesignSourceRegistry,
)
from domain.knowledge import (
    SourceDocument,
    SourceLocator,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.models import AskResult, Message
from domain.ports import LiveSourceReader
from infrastructure.config import DomainToolSettings, Settings, load_settings

ISSUE_LOCATOR = "acme/app#7"
ISSUE_SOURCE_ID = "issue:I_kwDOExample"

SUGGESTED_CANDIDATES = {
    "candidates": [
        {
            "candidate_id": "cand-1",
            "title": "Valid login",
            "category": "positive",
            "rationale": "Acceptance criteria require login.",
            "evidence_references": [
                {"source_type": "github", "source_id": ISSUE_SOURCE_ID}
            ],
        },
        {
            "candidate_id": "cand-2",
            "title": "Locked account",
            "category": "negative",
            "rationale": "Acceptance criteria mention lockout.",
            "evidence_references": [
                {"source_type": "github", "source_id": ISSUE_SOURCE_ID}
            ],
        },
        {
            "candidate_id": "cand-3",
            "title": "Long password",
            "category": "edge_case",
            "rationale": "Acceptance criteria bound password length.",
            "evidence_references": [
                {"source_type": "github", "source_id": ISSUE_SOURCE_ID}
            ],
        },
    ]
}

_GENERATED_CASES = {
    "cand-1": {
        "candidate_id": "cand-1",
        "test_type": "manual",
        "automation_fit": "applicable",
        "automation_rationale": "Stable UI flow.",
        "availability": "available",
        "preconditions": "A registered user exists",
        "steps": ["Open the login page", "Submit valid credentials"],
        "expected_result": "The dashboard is shown",
        "gherkin": "",
    },
    "cand-2": {
        "candidate_id": "cand-2",
        "test_type": "cucumber",
        "automation_fit": "applicable",
        "automation_rationale": "Scriptable lockout.",
        "availability": "available",
        "preconditions": "",
        "steps": [],
        "expected_result": "",
        "gherkin": (
            "Given a locked account\nWhen the user logs in\nThen an error is shown"
        ),
    },
}


def settings_with_pack(*, pack_on: bool = True, workspace_id: str = "ws-a") -> Settings:
    base = load_settings()
    return replace(
        base,
        domain_tools=DomainToolSettings(
            enabled_packs=("software-delivery",) if pack_on else ()
        ),
        document_catalog=replace(base.document_catalog, workspace_id=workspace_id),
    )


def issue_document(
    *, body: str = "Acceptance criteria: login, lockout, password length.",
    source_id: str = ISSUE_SOURCE_ID,
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(source_id, SourceType.GITHUB),
            title="Login",
            provider="github",
            content_format="markdown",
        ),
        f"# Login\n\n{body}",
    )


class RecordingIssueReader:
    """Live Issue reader double that records locators."""

    def __init__(self, document: SourceDocument | None = None) -> None:
        self.document = document or issue_document()
        self.error: Exception | None = None
        self.calls: list[SourceLocator] = []

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        self.calls.append(locator)
        if self.error is not None:
            raise self.error
        return self.document


class FakeTestDesignSource:
    """Registry source double: identity canonicalization and a recording reader."""

    __test__ = False

    def __init__(
        self,
        provider: str,
        *,
        reader: RecordingIssueReader | None = None,
        extracts: dict[str, str] | None = None,
        ambiguous: Collection[str] = (),
        reader_error: Exception | None = None,
        accepts: Callable[[str], bool] | None = None,
        canonicalize_error: Exception | None = None,
    ) -> None:
        self.provider = provider
        self.live_reader = reader or RecordingIssueReader()
        self.reader_calls = 0
        self._extracts = dict(extracts or {})
        self._ambiguous = frozenset(ambiguous)
        self._reader_error = reader_error
        self._accepts = accepts
        self._canonicalize_error = canonicalize_error

    def canonicalize(self, locator: str) -> str:
        if self._canonicalize_error is not None:
            raise self._canonicalize_error
        if not isinstance(locator, str) or not locator.strip():
            raise TestDesignValidationError("locator must be non-empty")
        if self._accepts is not None and not self._accepts(locator.strip()):
            raise TestDesignValidationError("locator is not for this source")
        return locator.strip()

    def extract_locator(self, text: str) -> str | None:
        if text in self._ambiguous:
            raise AmbiguousSourceLocatorError("Query must reference exactly one source")
        return self._extracts.get(text)

    def reader(self) -> LiveSourceReader:
        self.reader_calls += 1
        if self._reader_error is not None:
            raise self._reader_error
        return self.live_reader  # type: ignore[return-value]


class FakeTestDesignChat:
    """Chat double serving candidate suggestions and #300 case generation."""

    __test__ = False

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, system: str, messages: Sequence[Message], _settings: object
    ) -> AskResult:
        self.calls += 1
        if "test case author" in system:
            request = messages[-1].content
            cases = [
                case
                for candidate_id, case in _GENERATED_CASES.items()
                if f'"candidate_id":"{candidate_id}"' in request
            ]
            payload: Mapping[str, object] = {
                "cases": cases,
                "cucumber_feature": "Login",
                "cucumber_background": "Given the login page is open",
            }
        else:
            payload = SUGGESTED_CANDIDATES
        return AskResult(content=json.dumps(payload), model="fake")


def github_sources(
    *,
    reader: object | None = None,
    reader_factory: Callable[[str], object] | None = None,
    oauth_preflight: Callable[[], str] | None = None,
) -> TestDesignSourceRegistry:
    """Registry with the real GitHub source over offline preflight/reader doubles."""
    active_reader = reader or RecordingIssueReader()
    return TestDesignSourceRegistry(
        (
            GitHubTestDesignSource(
                preflight=oauth_preflight or (lambda: "token"),
                reader_factory=reader_factory or (lambda _token: active_reader),  # type: ignore[arg-type,return-value]
            ),
        )
    )


def build_fake_facade(
    tmp_path: Path,
    *,
    workspace_id: str = "ws-a",
    pack_on: bool = True,
    reader: RecordingIssueReader | None = None,
    chat: FakeTestDesignChat | None = None,
    oauth_preflight: Callable[[], str] | None = None,
    sources: TestDesignSourceRegistry | None = None,
) -> TestDesignFacade:
    active_chat = chat or FakeTestDesignChat()
    facade = TestDesignFacade(
        settings=settings_with_pack(pack_on=pack_on, workspace_id=workspace_id),
        store_path=tmp_path / "workspace.sqlite",
        workspace_id=workspace_id,
        sources=sources
        or github_sources(reader=reader, oauth_preflight=oauth_preflight),
    )
    facade._build_chat_model = lambda: active_chat  # type: ignore[method-assign]
    return facade
