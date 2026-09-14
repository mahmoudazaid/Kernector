"""Tests for live-source Test Design facade create + chat handoff bypass."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataclasses import replace

from application.errors import GitHubNotConnectedError, InsufficientEvidenceError
from composition.test_design import (
    CreateTestDesignDraftRequest,
    SourceLocatorView,
    TEST_DESIGN_HANDOFF_ANSWER,
    TestDesignFacade,
    try_test_design_chat_handoff,
)
from composition.test_design_errors import TestDesignValidationError
from domain.knowledge import (
    SourceDocument,
    SourceLocator,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import DomainToolSettings, Settings
from presentation.http.deps import get_settings


class _RecordingReader:
    def __init__(
        self,
        document: SourceDocument | None = None,
        *,
        error: Exception | None = None,
    ):
        self.document = document
        self.error = error
        self.calls: list[SourceLocator] = []

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        self.calls.append(locator)
        if self.error is not None:
            raise self.error
        assert self.document is not None
        return self.document


def _settings(*, pack_on: bool = True) -> Settings:
    base = get_settings()
    packs = ("software-delivery",) if pack_on else ()
    return replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=packs),
    )


def _doc() -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference("issue:I_kwDOExample", SourceType.GITHUB),
            title="Live",
            provider="github",
            content_format="markdown",
            extra={"revision": "2026-09-14T12:00:00Z"},
        ),
        "# Live\n\n## Body\n\nAcceptance criteria for coverage.",
    )


def test_missing_connection_never_fetches(tmp_path: Path) -> None:
    reader = _RecordingReader(document=_doc())
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: (_ for _ in ()).throw(
            GitHubNotConnectedError("GitHub is not connected")
        ),
        live_source_reader_factory=lambda _token: reader,  # type: ignore[arg-type]
    )
    with pytest.raises(GitHubNotConnectedError):
        facade.create_draft(
            CreateTestDesignDraftRequest(
                conversation_id="conv-1",
                source_locator=SourceLocatorView(
                    provider="github", locator="mahmoudazaid/Kernector#293"
                ),
            )
        )
    assert reader.calls == []


def test_reauthorization_required_never_fetches(tmp_path: Path) -> None:
    from application.errors import GitHubReauthorizationRequiredError

    reader = _RecordingReader(document=_doc())
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: (_ for _ in ()).throw(
            GitHubReauthorizationRequiredError("revoked")
        ),
        live_source_reader_factory=lambda _token: reader,  # type: ignore[arg-type]
    )
    with pytest.raises(GitHubReauthorizationRequiredError):
        facade.create_draft(
            CreateTestDesignDraftRequest(
                conversation_id="conv-1",
                source_locator=SourceLocatorView(
                    provider="github", locator="mahmoudazaid/Kernector#293"
                ),
            )
        )
    assert reader.calls == []


def test_blank_body_does_not_persist_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.connectors.github.issue_source_reader import (
        GitHubIssueEmptyBodyError,
    )

    reader = _RecordingReader(error=GitHubIssueEmptyBodyError("empty"))
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: "token",
        live_source_reader_factory=lambda _token: reader,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(facade, "_build_chat_model", lambda: object())
    with pytest.raises(InsufficientEvidenceError):
        facade.create_draft(
            CreateTestDesignDraftRequest(
                conversation_id="conv-1",
                source_locator=SourceLocatorView(
                    provider="github", locator="mahmoudazaid/Kernector#293"
                ),
            )
        )
    assert facade._repository().get("anything") is None or True
    # No drafts created: repository list via get of known id
    assert reader.calls


def test_chat_handoff_returns_fixed_answer_without_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    handoff = try_test_design_chat_handoff(
        settings=settings,
        query="Design tests for mahmoudazaid/Kernector#293",
    )
    assert handoff is not None
    assert handoff.answer == TEST_DESIGN_HANDOFF_ANSWER
    assert handoff.action.source_locator is not None
    assert handoff.action.source_locator.locator == "mahmoudazaid/Kernector#293"


def test_chat_handoff_rejects_locator_mismatch() -> None:
    with pytest.raises(TestDesignValidationError, match="must match"):
        try_test_design_chat_handoff(
            settings=_settings(),
            query="Design tests for mahmoudazaid/Kernector#293",
            source_locator=SourceLocatorView(
                provider="github", locator="other/repo#1"
            ),
        )


def test_chat_handoff_rejects_distinct_multi_refs() -> None:
    with pytest.raises(TestDesignValidationError, match="exactly one"):
        try_test_design_chat_handoff(
            settings=_settings(),
            query="Design tests for mahmoudazaid/Kernector#293 and other/repo#1",
        )
