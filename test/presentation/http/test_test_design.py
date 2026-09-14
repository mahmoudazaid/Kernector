"""HTTP tests for always-mounted test-design routes and chat action."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from composition.test_design import (
    ChatWorkflowActionView,
    CoverageGapView,
    CreateTestDesignDraftRequest,
    PatchTestDesignDraftRequest,
    SourceReferenceView,
    TestCandidateView,
    TestCoverageDraftView,
)
from composition.test_design_errors import (
    TestDesignNotFoundError,
    TestDesignUnavailableError,
    TestDesignVersionConflictError,
)
from presentation.http.app import create_app
from presentation.http.deps import get_settings, get_test_design_facade


@dataclass
class _StubFacade:
    enabled: bool = True
    draft: TestCoverageDraftView | None = None
    conflict: bool = False

    def create_draft(
        self, request: CreateTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        if not self.enabled:
            raise TestDesignUnavailableError("off")
        assert self.draft is not None
        return self.draft

    def get_draft(self, draft_id: str) -> TestCoverageDraftView:
        if not self.enabled:
            raise TestDesignUnavailableError("off")
        if self.draft is None or self.draft.draft_id != draft_id:
            raise TestDesignNotFoundError("missing")
        return self.draft

    def patch_draft(
        self, draft_id: str, request: PatchTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        if not self.enabled:
            raise TestDesignUnavailableError("off")
        if self.conflict:
            raise TestDesignVersionConflictError("stale")
        return self.get_draft(draft_id)

    def generate_scenarios(
        self, draft_id: str, *, expected_version: int
    ) -> TestCoverageDraftView:
        return self.get_draft(draft_id)

    def confirm_draft(
        self, draft_id: str, *, expected_version: int
    ) -> TestCoverageDraftView:
        return self.get_draft(draft_id)


def _draft_view() -> TestCoverageDraftView:
    return TestCoverageDraftView(
        draft_id="draft-1",
        workspace_id="ws-1",
        conversation_id="conv-1",
        source_reference=SourceReferenceView("PROJ-42", "jira"),
        ticket_identifier="KERN-293",
        status="coverage_review",
        candidates=(
            TestCandidateView(
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                rationale="AC",
                evidence_references=(SourceReferenceView("PROJ-42", "jira"),),
                selected=True,
                origin="suggested",
            ),
        ),
        scenarios=(),
        coverage_gaps=(
            CoverageGapView(
                category="negative",
                detail="No ACL criteria.",
            ),
        ),
        version=1,
        selected_candidate_ids=("cand-1",),
    )


def _client(facade: _StubFacade) -> TestClient:
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    return TestClient(app)


def test_openapi_always_lists_test_design_paths_and_chat_action() -> None:
    schema = TestClient(create_app(cors_origins=())).get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/test-design/drafts" in paths
    assert "/api/v1/test-design/drafts/{draft_id}" in paths
    assert "/api/v1/test-design/drafts/{draft_id}/scenarios" in paths
    assert "/api/v1/test-design/drafts/{draft_id}/confirm" in paths
    components = schema["components"]["schemas"]
    assert "ChatWorkflowActionResponse" in components
    assert "TestCoverageDraftResponse" in components
    ask = components["ChatAskResponse"]["properties"]
    assert "action" in ask


def test_pack_disabled_returns_unavailable_404() -> None:
    client = _client(_StubFacade(enabled=False, draft=_draft_view()))
    response = client.get("/api/v1/test-design/drafts/draft-1")
    assert response.status_code == 404
    assert response.json()["code"] == "test_design_unavailable"


def test_missing_draft_returns_not_found_404() -> None:
    client = _client(_StubFacade(enabled=True, draft=_draft_view()))
    response = client.get("/api/v1/test-design/drafts/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "test_design_not_found"


def test_version_conflict_returns_409() -> None:
    client = _client(
        _StubFacade(enabled=True, draft=_draft_view(), conflict=True)
    )
    response = client.patch(
        "/api/v1/test-design/drafts/draft-1",
        json={"expected_version": 1, "candidates": []},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "test_design_version_conflict"


def test_get_draft_returns_projection() -> None:
    client = _client(_StubFacade(enabled=True, draft=_draft_view()))
    response = client.get("/api/v1/test-design/drafts/draft-1")
    assert response.status_code == 200
    body = response.json()
    assert body["draft_id"] == "draft-1"
    assert body["ticket_identifier"] == "KERN-293"
    assert body["version"] == 1
    assert body["candidates"][0]["candidate_id"] == "cand-1"


def test_resolve_action_helper_requires_pack_and_locator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from composition import test_design as module
    from composition.test_design import SourceLocatorView

    settings = get_settings()

    monkeypatch.setattr(
        module, "software_delivery_tools_enabled", lambda _s: False
    )
    assert (
        module.resolve_start_test_design_action(
            settings=settings,
            source_locator=SourceLocatorView(
                provider="github", locator="mahmoudazaid/Kernector#293"
            ),
        )
        is None
    )

    monkeypatch.setattr(
        module, "software_delivery_tools_enabled", lambda _s: True
    )
    action = module.resolve_start_test_design_action(
        settings=settings,
        source_locator=SourceLocatorView(
            provider="github", locator="mahmoudazaid/Kernector#293"
        ),
    )
    assert action == ChatWorkflowActionView(
        kind="start_workflow",
        workflow_id="software-delivery.test-design",
        label="Start Test Design",
        source_locator=SourceLocatorView(
            provider="github", locator="mahmoudazaid/Kernector#293"
        ),
    )
    assert (
        module.resolve_start_test_design_action(
            settings=settings,
            source_locator=None,
        )
        is None
    )
