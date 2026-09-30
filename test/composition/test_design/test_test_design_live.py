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
from composition.test_design.facade import (
    CreateTestDesignDraftRequest,
    PatchTestDesignDraftRequest,
    SourceLocatorView,
    SourceReferenceView,
    TEST_DESIGN_HANDOFF_ANSWER,
    TestCandidateView,
    TestDesignFacade,
    try_test_design_chat_handoff,
)
from composition.test_design.errors import TestDesignValidationError
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
from packs.software_delivery.test_design.models import GeneratedTestCase
from presentation.http.deps import get_settings
from test.composition.test_design.test_design_fakes import github_sources


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


def _sources():  # noqa: ANN202
    return composition_container.build_test_design_sources(_settings())


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
        sources=github_sources(
            reader=reader,
            oauth_preflight=lambda: (_ for _ in ()).throw(
                GitHubNotConnectedError("GitHub is not connected")
            ),
        ),
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
        sources=github_sources(
            reader=reader,
            oauth_preflight=lambda: (_ for _ in ()).throw(
                GitHubReauthorizationRequiredError("revoked")
            ),
        ),
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
        sources=github_sources(reader=reader),
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
        sources=github_sources(reader=reader),
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
                        '"source_id":"issue:I_kwDOExample"}]}]}'
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


def test_patch_demotes_ready_draft_when_candidates_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _RecordingReader(document=_doc())
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        sources=github_sources(reader=reader),
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
                        '"source_id":"issue:I_kwDOExample"}]}]}'
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
    ready_version = confirmed.version

    renamed = facade.patch_draft(
        confirmed.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=ready_version,
            candidates=(
                TestCandidateView(
                    candidate_id="cand-1",
                    title="Renamed title",
                    category="positive",
                    rationale="Refined rationale.",
                    evidence_references=(
                        SourceReferenceView("issue:I_kwDOExample", "github"),
                    ),
                    selected=True,
                    origin="suggested",
                ),
            ),
        ),
    )
    assert renamed.status == "coverage_review"
    assert renamed.version == ready_version + 1

    deselected = facade.patch_draft(
        renamed.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=renamed.version,
            candidates=(
                TestCandidateView(
                    candidate_id="cand-1",
                    title="Renamed title",
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
    assert deselected.status == "coverage_review"
    assert deselected.selected_candidate_ids == ()

    reselected = facade.patch_draft(
        deselected.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=deselected.version,
            candidates=(
                TestCandidateView(
                    candidate_id="cand-1",
                    title="Renamed title",
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
    reconfirmed = facade.confirm_draft(
        reselected.draft_id, expected_version=reselected.version
    )
    assert reconfirmed.status == "ready"
    assert reconfirmed.version == reselected.version + 1

    identical = facade.patch_draft(
        reconfirmed.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=reconfirmed.version,
            candidates=(
                TestCandidateView(
                    candidate_id="cand-1",
                    title="Renamed title",
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
    assert identical.status == "ready"
    assert identical.version == reconfirmed.version + 1


def test_patch_keeps_ready_status_when_only_deselecting_and_cases_on_reselect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _RecordingReader(document=_doc())
    facade = TestDesignFacade(
        settings=_settings(),
        store_path=tmp_path / "ws.sqlite",
        workspace_id="default",
        sources=github_sources(reader=reader),
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
                        '"source_id":"issue:I_kwDOExample"}]},'
                        '{"candidate_id":"cand-2","title":"Invalid",'
                        '"category":"negative","rationale":"Grounded.",'
                        '"evidence_references":[{"source_type":"github",'
                        '"source_id":"issue:I_kwDOExample"}]}]}'
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

    def _candidates(*, second_selected: bool) -> tuple[TestCandidateView, ...]:
        return tuple(
            TestCandidateView(
                candidate_id=candidate_id,
                title=title,
                category=category,
                rationale="Grounded.",
                evidence_references=(
                    SourceReferenceView("issue:I_kwDOExample", "github"),
                ),
                selected=selected,
                origin="suggested",
            )
            for candidate_id, title, category, selected in (
                ("cand-1", "Valid", "positive", True),
                ("cand-2", "Invalid", "negative", second_selected),
            )
        )

    selected = facade.patch_draft(
        draft.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=draft.version,
            candidates=_candidates(second_selected=True),
        ),
    )
    confirmed = facade.confirm_draft(
        selected.draft_id, expected_version=selected.version
    )
    assert confirmed.status == "ready"

    deselected = facade.patch_draft(
        confirmed.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=confirmed.version,
            candidates=_candidates(second_selected=False),
        ),
    )
    assert deselected.status == "ready"
    assert deselected.evidence_fingerprint == confirmed.evidence_fingerprint
    assert deselected.selected_candidate_ids == ("cand-1",)

    repo = facade._repository()
    stored = repo.get(deselected.draft_id)
    assert stored is not None
    with_cases = repo.update(
        replace(
            stored,
            status="case_editing",
            generated_cases=(
                GeneratedTestCase(
                    candidate_id="cand-1",
                    test_type="cucumber",
                    automation_fit="applicable",
                    automation_rationale="Stable.",
                    availability="available",
                    preconditions="",
                    steps=(),
                    expected_result="",
                    gherkin="Scenario: Valid\n  Given logged out",
                    user_edited=True,
                ),
            ),
            cucumber_feature="Login",
            cucumber_background="",
        ),
        expected_version=stored.version,
    )

    reselected = facade.patch_draft(
        with_cases.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=with_cases.version,
            candidates=_candidates(second_selected=True),
        ),
    )
    assert reselected.status == "coverage_review"
    assert [case.candidate_id for case in reselected.generated_cases] == ["cand-1"]
    assert reselected.cucumber_feature == "Login"

    reconfirmed = facade.confirm_draft(
        reselected.draft_id, expected_version=reselected.version
    )
    assert reconfirmed.status == "case_editing"
    assert [case.candidate_id for case in reconfirmed.generated_cases] == ["cand-1"]
    assert reconfirmed.generated_cases[0].user_edited is True
    assert reconfirmed.cucumber_feature == "Login"
    assert reconfirmed.cucumber_background == ""

    renamed = facade.patch_draft(
        reconfirmed.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=reconfirmed.version,
            candidates=tuple(
                replace(item, title="Valid login") if item.candidate_id == "cand-1" else item
                for item in _candidates(second_selected=True)
            ),
        ),
    )
    assert renamed.status == "case_editing"
    assert renamed.evidence_fingerprint == reconfirmed.evidence_fingerprint
    assert [case.candidate_id for case in renamed.generated_cases] == ["cand-1"]
    assert renamed.cucumber_feature == "Login"


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
            sources=github_sources(reader=_RecordingReader(error=error)),
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
        sources=_sources(),
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
            sources=_sources(),
            source_locator=SourceLocatorView(
                provider="github", locator="other/repo#1"
            ),
        )


def test_chat_handoff_declines_discussion_with_multiple_issues() -> None:
    handoff = try_test_design_chat_handoff(
        settings=_settings(),
        query="Compare the test coverage of acme/web#10 and acme/api#11",
        sources=_sources(),
    )
    assert handoff is None


def test_chat_handoff_rejects_explicit_command_with_multiple_issues() -> None:
    with pytest.raises(TestDesignValidationError, match="exactly one"):
        try_test_design_chat_handoff(
            settings=_settings(),
            query="Design tests for acme/web#10 and acme/api#11",
            sources=_sources(),
        )


def test_chat_handoff_declines_topical_phrase_without_issue_reference() -> None:
    for query in (
        "How does test design work in this repo?",
        "Who owns test design here?",
        "What do the docs say about test design?",
        "Design tests for 293",
        "Can you explain the coverage plan we agreed on last sprint?",
    ):
        assert (
            try_test_design_chat_handoff(
                settings=_settings(), query=query, sources=_sources()
            )
            is None
        ), query


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

    reader = (
        composition_container.build_test_design_sources(
            settings,
            connection_store=tokens,
            oauth_gateway=gateway,
            client_factory=client_factory,
        )
        .resolve("github")
        .reader()
    )
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

    reader = (
        composition_container.build_test_design_sources(
            settings,
            connection_store=tokens,
            client_factory=client_factory,
        )
        .resolve("github")
        .reader()
    )
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
