"""HTTP tests for always-mounted test-design routes and chat action."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from composition.test_design import (
    ChatWorkflowActionView,
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
from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from domain.models import AskResult
from infrastructure.config import DomainToolSettings
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
        version=1,
        selected_candidate_ids=("cand-1",),
    )


def _client(facade: _StubFacade) -> TestClient:
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    return TestClient(app)


class _HTTPReader:
    def fetch(self, _locator):
        return SourceDocument(
            SourceMetadata(
                reference=SourceReference("issue:I_http", SourceType.GITHUB),
                title="Live",
                provider="github",
                content_format="markdown",
                extra={"revision": "2026-09-14T12:00:00Z"},
            ),
            "Acceptance criteria for coverage.",
        )


class _HTTPChat:
    def complete(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return AskResult(
            content=(
                '{"candidates":[{"candidate_id":"cand-1","title":"Valid",'
                '"category":"positive","rationale":"Grounded.",'
                '"evidence_references":[{"source_type":"github",'
                '"source_id":"issue:I_http"}]}]}'
            ),
            model="fake",
        )


def _real_facade_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from composition.test_design import TestDesignFacade

    from dataclasses import replace

    settings = replace(
        get_settings(),
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    facade = TestDesignFacade(
        settings=settings,
        store_path=tmp_path / "workspace.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: "token",
        live_source_reader_factory=lambda _token: _HTTPReader(),
    )
    monkeypatch.setattr(facade, "_build_chat_model", lambda: _HTTPChat())
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    return TestClient(app)


def _created_draft(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/test-design/drafts",
        json={
            "conversation_id": "conv-1",
            "source_locator": {
                "provider": "github",
                "locator": "mahmoudazaid/Kernector#293",
            },
        },
    )
    assert response.status_code == 200
    return response.json()


def test_openapi_always_lists_test_design_paths_and_chat_action() -> None:
    schema = TestClient(create_app(cors_origins=())).get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/test-design/drafts" in paths
    assert "/api/v1/test-design/drafts/{draft_id}" in paths
    assert "/api/v1/test-design/drafts/{draft_id}/scenarios" not in paths
    assert "/api/v1/test-design/drafts/{draft_id}/confirm" in paths
    assert "/api/v1/test-design/drafts/{draft_id}/export/google-drive" in paths
    components = schema["components"]["schemas"]
    assert "ChatWorkflowActionResponse" in components
    assert "TestCoverageDraftResponse" in components
    assert "ExportTestDesignGoogleDriveRequest" in components
    assert "ExportTestDesignGoogleDriveResponse" in components
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


@pytest.mark.parametrize(
    "candidate_patch",
    [
        {"title": " ", "category": "positive", "candidate_id": "cand-1"},
        {"title": "Valid", "category": "smoke", "candidate_id": "cand-1"},
    ],
)
def test_real_facade_patch_invalid_candidate_returns_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_patch: dict[str, str],
) -> None:
    client = _real_facade_client(tmp_path, monkeypatch)
    draft = _created_draft(client)
    candidate = draft["candidates"][0] | candidate_patch

    response = client.patch(
        f"/api/v1/test-design/drafts/{draft['draft_id']}",
        json={"expected_version": draft["version"], "candidates": [candidate]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["detail"] == "The test-design request was invalid."


def test_real_facade_patch_duplicate_candidate_ids_returns_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _real_facade_client(tmp_path, monkeypatch)
    draft = _created_draft(client)
    candidate = draft["candidates"][0]

    response = client.patch(
        f"/api/v1/test-design/drafts/{draft['draft_id']}",
        json={
            "expected_version": draft["version"],
            "candidates": [candidate, candidate | {"title": "Other"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_real_facade_patch_demotes_ready_after_semantic_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _real_facade_client(tmp_path, monkeypatch)
    draft = _created_draft(client)
    candidate = draft["candidates"][0] | {"selected": True}

    selected = client.patch(
        f"/api/v1/test-design/drafts/{draft['draft_id']}",
        json={"expected_version": draft["version"], "candidates": [candidate]},
    )
    assert selected.status_code == 200
    confirmed = client.post(
        f"/api/v1/test-design/drafts/{draft['draft_id']}/confirm",
        json={"expected_version": selected.json()["version"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "ready"
    ready_version = confirmed.json()["version"]

    renamed = client.patch(
        f"/api/v1/test-design/drafts/{draft['draft_id']}",
        json={
            "expected_version": ready_version,
            "candidates": [candidate | {"title": "Edited after confirm"}],
        },
    )
    assert renamed.status_code == 200
    body = renamed.json()
    assert body["status"] == "coverage_review"
    assert body["version"] == ready_version + 1

    reconfirmed = client.post(
        f"/api/v1/test-design/drafts/{draft['draft_id']}/confirm",
        json={"expected_version": body["version"]},
    )
    assert reconfirmed.status_code == 200
    assert reconfirmed.json()["status"] == "ready"
    assert reconfirmed.json()["version"] == body["version"] + 1
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
