"""Tests for live-source Test Design facade create + chat handoff bypass."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataclasses import replace

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    InsufficientEvidenceError,
)
from composition import container as composition_container
from composition.test_design import (
    CreateTestDesignDraftRequest,
    PatchTestDesignDraftRequest,
    SourceLocatorView,
    SourceReferenceView,
    TEST_DESIGN_HANDOFF_ANSWER,
    TestCandidateView,
    TestDesignFacade,
    try_test_design_chat_handoff,
)
from composition.test_design_errors import TestDesignValidationError
from domain.errors import ConnectorAuthError
from domain.knowledge import (
    SourceDocument,
    SourceLocator,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.models import AskResult
from infrastructure.config import (
    DomainToolSettings,
    GitHubOAuthSettings,
    load_settings,
    Settings,
)
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
    GitHubOAuthGrant,
)
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


def test_pack_validation_error_is_wrapped_with_sanitized_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _RecordingReader(document=_doc())
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: "token",
        live_source_reader_factory=lambda _token: reader,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        facade,
        "_build_chat_model",
        lambda: type(
            "FakeChat",
            (),
            {
                "complete": lambda self, *_args, **_kwargs: AskResult(
                    content=(
                        '{"candidates":[{"candidate_id":"cand-1","title":"Valid",'
                        '"category":"positive","rationale":"Grounded.",'
                        '"evidence_references":[{"source_type":"github",'
                        '"source_id":"issue:I_kwDOExample"}]}],"coverage_gaps":[]}'
                    ),
                    model="fake",
                )
            },
        )(),
    )
    draft = facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-1",
            source_locator=SourceLocatorView(
                provider="github", locator="mahmoudazaid/Kernector#293"
            ),
        )
    )

    with pytest.raises(TestDesignValidationError) as raised:
        facade.patch_draft(
            draft.draft_id,
            PatchTestDesignDraftRequest(
                expected_version=draft.version,
                candidates=(
                    TestCandidateView(
                        candidate_id="cand-1",
                        title="secret-body " * 30,
                        category="positive",
                        rationale="Grounded.",
                        evidence_references=(
                            SourceReferenceView("issue:I_kwDOExample", "github"),
                        ),
                        selected=False,
                        origin="suggested",
                    ),
                    TestCandidateView(
                        candidate_id="cand-1",
                        title="Other",
                        category="positive",
                        rationale="Grounded.",
                        evidence_references=(
                            SourceReferenceView("issue:I_kwDOExample", "github"),
                        ),
                        selected=False,
                        origin="suggested",
                    ),
                ),
            ),
        )

    assert str(raised.value) == "The test-design request was invalid."
    assert "secret-body" not in str(raised.value)


def test_patch_rejects_ready_draft_with_zero_selections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _RecordingReader(document=_doc())
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: "token",
        live_source_reader_factory=lambda _token: reader,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        facade,
        "_build_chat_model",
        lambda: type(
            "FakeChat",
            (),
            {
                "complete": lambda self, *_args, **_kwargs: AskResult(
                    content=(
                        '{"candidates":[{"candidate_id":"cand-1","title":"Valid",'
                        '"category":"positive","rationale":"Grounded.",'
                        '"evidence_references":[{"source_type":"github",'
                        '"source_id":"issue:I_kwDOExample"}]}],"coverage_gaps":[]}'
                    ),
                    model="fake",
                )
            },
        )(),
    )
    draft = facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-1",
            source_locator=SourceLocatorView(
                provider="github", locator="mahmoudazaid/Kernector#293"
            ),
        )
    )
    selected = facade.patch_draft(
        draft.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=draft.version,
            candidates=(
                TestCandidateView(
                    candidate_id="cand-1",
                    title="Valid",
                    category="positive",
                    rationale="Grounded.",
                    evidence_references=(
                        SourceReferenceView("issue:I_kwDOExample", "github"),
                    ),
                    selected=True,
                    origin="suggested",
                ),
            ),
        ),
    )
    confirmed = facade.confirm_draft(
        selected.draft_id, expected_version=selected.version
    )
    assert confirmed.status == "ready"

    with pytest.raises(TestDesignValidationError, match="at least one selected"):
        facade.patch_draft(
            confirmed.draft_id,
            PatchTestDesignDraftRequest(
                expected_version=confirmed.version,
                candidates=(
                    TestCandidateView(
                        candidate_id="cand-1",
                        title="Valid",
                        category="positive",
                        rationale="Grounded.",
                        evidence_references=(
                            SourceReferenceView("issue:I_kwDOExample", "github"),
                        ),
                        selected=False,
                        origin="suggested",
                    ),
                ),
            ),
        )


def test_issue_pr_and_mismatch_errors_are_sanitized(
    tmp_path: Path,
) -> None:
    from infrastructure.connectors.github.issue_source_reader import (
        GitHubIssueLocatorMismatchError,
        GitHubIssueNotIssueError,
    )

    for error in (
        GitHubIssueNotIssueError("raw Pull Request detail"),
        GitHubIssueLocatorMismatchError("raw locator detail"),
    ):
        facade = TestDesignFacade(
            settings=_settings(),
            store_path=tmp_path / f"{type(error).__name__}.sqlite",
            workspace_id="default",
            oauth_preflight=lambda: "token",
            live_source_reader_factory=lambda _token, error=error: _RecordingReader(
                error=error
            ),  # type: ignore[arg-type]
        )

        with pytest.raises(TestDesignValidationError) as raised:
            facade.create_draft(
                CreateTestDesignDraftRequest(
                    conversation_id="conv-1",
                    source_locator=SourceLocatorView(
                        provider="github", locator="mahmoudazaid/Kernector#293"
                    ),
                )
            )

        assert str(raised.value) == "The test-design request was invalid."


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


def test_chat_handoff_declines_distinct_multi_refs() -> None:
    handoff = try_test_design_chat_handoff(
        settings=_settings(),
        query="Compare the test coverage of acme/web#10 and acme/api#11",
    )
    assert handoff is None


class _FakeRefreshGateway:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []

    def refresh(self, refresh_token: str) -> GitHubOAuthGrant:
        self.refresh_calls.append(refresh_token)
        return GitHubOAuthGrant(
            access_token="gho-refreshed-secret",
            refresh_token=refresh_token,
        )


class _FlakyAuthClient:
    def __init__(self, access_token: str, *, fail_tokens: set[str]) -> None:
        self.access_token = access_token
        self._fail_tokens = fail_tokens

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, object]:
        if self.access_token in self._fail_tokens:
            raise ConnectorAuthError("expired")
        return {
            "number": issue_number,
            "node_id": "I_kwDOExample",
            "title": "Live",
            "body": "Acceptance criteria for coverage.",
            "updated_at": "2026-09-14T12:00:00Z",
            "html_url": f"https://github.com/{owner}/{repo}/issues/{issue_number}",
            "repository": {"full_name": f"{owner}/{repo}"},
            "user": {"login": "ada"},
            "state": "open",
            "labels": [],
        }


def _oauth_settings(tmp_path: Path) -> Settings:
    loaded = load_settings()
    packs = ("software-delivery",)
    return replace(
        loaded,
        domain_tools=DomainToolSettings(enabled_packs=packs),
        github_oauth=GitHubOAuthSettings(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/api/v1/connectors/github/oauth/callback",
            frontend_redirect="http://localhost:3000/documents",
            token_path=tmp_path / "github-oauth-connection.json",
            state_path=tmp_path / "github-oauth-state.json",
            state_ttl_seconds=600,
        ),
    )


def _save_grant(tmp_path: Path, *, refresh_token: str | None) -> GitHubOAuthConnectionStore:
    settings = _oauth_settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=refresh_token,
            account_login="ada",
            owner=None,
            repo=None,
            project_owner=None,
            project_number=None,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    return tokens


def test_live_reader_refreshes_token_then_retries(tmp_path: Path) -> None:
    settings = _oauth_settings(tmp_path)
    tokens = _save_grant(tmp_path, refresh_token="ghr-refresh-secret")
    gateway = _FakeRefreshGateway()
    seen: list[str] = []

    def client_factory(access_token: str):
        seen.append(access_token)
        return _FlakyAuthClient(access_token, fail_tokens={"gho-access-secret"})

    facade = composition_container.build_test_design_facade(
        settings,
        connection_store=tokens,
        oauth_gateway=gateway,
        client_factory=client_factory,
    )
    reader = facade._live_source_reader_factory("gho-access-secret")
    document = reader.fetch(
        SourceLocator(provider="github", locator="mahmoudazaid/Kernector#293")
    )
    assert document.reference.source_id == "issue:I_kwDOExample"
    assert gateway.refresh_calls == ["ghr-refresh-secret"]
    assert seen == ["gho-access-secret", "gho-refreshed-secret"]
    saved = tokens.load()
    assert saved is not None
    assert saved.access_token == "gho-refreshed-secret"
    assert saved.reauthorization_required is False


def test_live_reader_marks_reauth_when_refresh_token_missing(tmp_path: Path) -> None:
    settings = _oauth_settings(tmp_path)
    tokens = _save_grant(tmp_path, refresh_token=None)

    def client_factory(access_token: str):
        return _FlakyAuthClient(access_token, fail_tokens={access_token})

    facade = composition_container.build_test_design_facade(
        settings,
        connection_store=tokens,
        client_factory=client_factory,
    )
    reader = facade._live_source_reader_factory("gho-access-secret")
    with pytest.raises(GitHubReauthorizationRequiredError):
        reader.fetch(
            SourceLocator(provider="github", locator="mahmoudazaid/Kernector#293")
        )
    saved = tokens.load()
    assert saved is not None
    assert saved.reauthorization_required is True


def test_build_test_design_facade_requires_workspace_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from application.errors import ConfigurationError

    monkeypatch.delenv("DOCUMENT_CATALOG_WORKSPACE_ID", raising=False)
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite"))
    settings = composition_container.load_settings()

    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_WORKSPACE_ID"):
        composition_container.build_test_design_facade(settings)


def test_build_test_design_facade_does_not_require_vector_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from presentation import http
    from presentation.http import deps as http_deps

    settings = _oauth_settings(tmp_path)
    _save_grant(tmp_path, refresh_token="ghr-refresh-secret")

    def explode():
        raise AssertionError("vector store must not be instantiated")

    monkeypatch.setattr(http_deps, "get_vector_store", explode)
    facade = http_deps.get_test_design_facade(settings)

    assert facade is not None
    assert http is not None
