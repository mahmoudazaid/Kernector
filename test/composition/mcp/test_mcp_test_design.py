"""Composition MCP Test Design workflow adapter over the existing facade (#338)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    SourceReauthorizationRequiredError,
)
from composition.mcp.test_design import McpTestDesignOperations, McpTestDesignWorkflow
from composition.test_design.facade import TestDesignFacade
from domain.errors import (
    ConnectorNotFoundError,
    ToolArgumentValidationError,
    ToolEvidenceChangedError,
    ToolInsufficientEvidenceError,
    ToolSourceNotConnectedError,
    ToolTargetNotFoundError,
    ToolUnavailableError,
    ToolUnsupportedSourceError,
    ToolVersionConflictError,
)
from test.composition.test_design.test_design_fakes import (
    ISSUE_LOCATOR,
    RecordingIssueReader,
    build_fake_facade,
    issue_document,
)


def _workflow(
    tmp_path: Path, **kwargs
) -> tuple[McpTestDesignOperations, TestDesignFacade]:
    facade = build_fake_facade(tmp_path, **kwargs)
    return McpTestDesignOperations(facade), facade


def test_start_generates_server_side_conversation_id(tmp_path: Path) -> None:
    workflow, facade = _workflow(tmp_path)

    draft = workflow.start(issue_locator=ISSUE_LOCATOR)

    assert draft.status == "coverage_review"
    assert draft.version == 1
    assert [c.candidate_id for c in draft.candidates] == [
        "cand-1",
        "cand-2",
        "cand-3",
    ]
    stored = facade.get_draft(draft.draft_id)
    assert stored.conversation_id.startswith("mcp-")
    assert len(stored.conversation_id) > len("mcp-")


def test_start_never_reuses_a_conversation_id(tmp_path: Path) -> None:
    workflow, facade = _workflow(tmp_path)

    first = workflow.start(issue_locator=ISSUE_LOCATOR)
    second = workflow.start(issue_locator=ISSUE_LOCATOR)

    assert (
        facade.get_draft(first.draft_id).conversation_id
        != facade.get_draft(second.draft_id).conversation_id
    )


def test_confirm_patches_selection_then_confirms(tmp_path: Path) -> None:
    workflow, _facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)

    confirmed = workflow.confirm_selection(
        draft_id=started.draft_id,
        expected_version=started.version,
        candidate_ids=("cand-1", "cand-2"),
    )

    assert confirmed.status == "ready"
    assert confirmed.version == started.version + 2
    assert tuple(confirmed.selected_candidate_ids) == ("cand-1", "cand-2")
    assert [c.selected for c in confirmed.candidates] == [True, True, False]


def test_confirm_on_ready_draft_with_same_selection_advances_once(
    tmp_path: Path,
) -> None:
    workflow, _facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)
    ready = workflow.confirm_selection(
        draft_id=started.draft_id,
        expected_version=started.version,
        candidate_ids=("cand-1",),
    )

    again = workflow.confirm_selection(
        draft_id=ready.draft_id,
        expected_version=ready.version,
        candidate_ids=("cand-1",),
    )

    assert again.status == "ready"
    assert again.version == ready.version + 1


def test_confirm_with_stale_version_is_conflict_without_write(tmp_path: Path) -> None:
    workflow, facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)

    with pytest.raises(ToolVersionConflictError):
        workflow.confirm_selection(
            draft_id=started.draft_id,
            expected_version=started.version + 5,
            candidate_ids=("cand-1",),
        )

    stored = facade.get_draft(started.draft_id)
    assert stored.version == started.version
    assert stored.selected_candidate_ids == ()


def test_confirm_with_unknown_candidate_is_validation_without_write(
    tmp_path: Path,
) -> None:
    workflow, facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)

    with pytest.raises(ToolArgumentValidationError):
        workflow.confirm_selection(
            draft_id=started.draft_id,
            expected_version=started.version,
            candidate_ids=("cand-1", "cand-404"),
        )

    stored = facade.get_draft(started.draft_id)
    assert stored.version == started.version
    assert stored.selected_candidate_ids == ()


def test_confirm_evidence_changed_keeps_saved_selection(tmp_path: Path) -> None:
    reader = RecordingIssueReader()
    workflow, facade = _workflow(tmp_path, reader=reader)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)
    reader.document = issue_document(source_id="issue:I_other")

    with pytest.raises(ToolEvidenceChangedError):
        workflow.confirm_selection(
            draft_id=started.draft_id,
            expected_version=started.version,
            candidate_ids=("cand-1",),
        )

    stored = facade.get_draft(started.draft_id)
    assert stored.status == "coverage_review"
    assert stored.version == started.version + 1
    assert stored.selected_candidate_ids == ("cand-1",)


@pytest.mark.parametrize(
    "error",
    [
        GitHubNotConnectedError("GitHub is not connected"),
        GitHubReauthorizationRequiredError("token revoked"),
        SourceReauthorizationRequiredError("grant rejected"),
    ],
)
def test_source_grant_errors_map_to_source_not_connected(
    tmp_path: Path, error: Exception
) -> None:
    def _preflight() -> str:
        raise error

    workflow, _facade = _workflow(tmp_path, oauth_preflight=_preflight)

    with pytest.raises(ToolSourceNotConnectedError):
        workflow.start(issue_locator=ISSUE_LOCATOR)


def test_blank_issue_maps_to_insufficient_evidence(tmp_path: Path) -> None:
    from infrastructure.connectors.github.issue_source_reader import (
        GitHubIssueEmptyBodyError,
    )

    reader = RecordingIssueReader()
    reader.error = GitHubIssueEmptyBodyError("empty body")
    workflow, _facade = _workflow(tmp_path, reader=reader)

    with pytest.raises(ToolInsufficientEvidenceError):
        workflow.start(issue_locator=ISSUE_LOCATOR)


def test_missing_source_issue_maps_to_target_not_found(tmp_path: Path) -> None:
    reader = RecordingIssueReader()
    reader.error = ConnectorNotFoundError("issue not found")
    workflow, _facade = _workflow(tmp_path, reader=reader)

    with pytest.raises(ToolTargetNotFoundError):
        workflow.start(issue_locator=ISSUE_LOCATOR)


@pytest.mark.parametrize("locator", ["not a locator", "ENG-7"])
def test_locator_no_registered_source_accepts_maps_to_unsupported_source(
    tmp_path: Path, locator: str
) -> None:
    workflow, _facade = _workflow(tmp_path)

    with pytest.raises(ToolUnsupportedSourceError):
        workflow.start(issue_locator=locator)


class _JiraIssueClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_issue(self, key: str, fields: object) -> dict[str, object]:
        self.calls.append(key)
        return {
            "id": "10001",
            "key": key,
            "fields": {
                "summary": "Login",
                "description": "Acceptance criteria: login, lockout, password length.",
                "updated": "2026-09-14T12:00:00.000+0000",
            },
        }


def _github_and_jira(tmp_path: Path, client: _JiraIssueClient):  # noqa: ANN202
    from composition.test_design.jira_data_center_source import (
        JiraDataCenterTestDesignSource,
    )
    from composition.test_design.sources import TestDesignSourceRegistry
    from infrastructure.config import JiraDataCenterSettings
    from infrastructure.connectors.jira.data_center_state import (
        JiraDataCenterStateStore,
    )
    from test.composition.test_design.test_design_fakes import github_sources

    settings = JiraDataCenterSettings(
        base_url="https://jira.example.com/jira",
        token="dc-token",
        state_path=tmp_path / "jira-dc-connection.json",
    )
    jira = JiraDataCenterTestDesignSource(
        settings_provider=lambda: settings,
        state_store=JiraDataCenterStateStore(settings.state_path),
        client_factory=lambda _base_url, _token: client,
    )
    github = github_sources().resolve("github")
    return TestDesignSourceRegistry((github, jira))


@pytest.mark.parametrize(
    "locator", ["ENG-7", "https://jira.example.com/jira/browse/ENG-7"]
)
def test_start_resolves_a_jira_issue_locator_through_the_registry(
    tmp_path: Path, locator: str
) -> None:
    client = _JiraIssueClient()
    workflow, _facade = _workflow(tmp_path, sources=_github_and_jira(tmp_path, client))

    draft = workflow.start(issue_locator=locator)

    assert client.calls == ["ENG-7"]
    assert draft.ticket_identifier == "ENG-7"
    assert draft.source_reference.source_type == "jira"
    assert draft.source_reference.source_id == "issue:10001"


def test_start_resolves_a_github_locator_when_jira_is_registered(
    tmp_path: Path,
) -> None:
    client = _JiraIssueClient()
    workflow, _facade = _workflow(tmp_path, sources=_github_and_jira(tmp_path, client))

    draft = workflow.start(issue_locator=ISSUE_LOCATOR)

    assert client.calls == []
    assert draft.source_reference.source_type == "github"


def test_start_with_foreign_instance_url_is_unsupported_source(tmp_path: Path) -> None:
    client = _JiraIssueClient()
    workflow, _facade = _workflow(tmp_path, sources=_github_and_jira(tmp_path, client))

    with pytest.raises(ToolUnsupportedSourceError):
        workflow.start(issue_locator="https://other.example.com/browse/ENG-7")
    assert client.calls == []


def test_start_args_describe_both_locator_families_without_provider() -> None:
    from composition.mcp.test_design import TestDesignStartArgs

    schema = TestDesignStartArgs.model_json_schema()

    assert set(schema["properties"]) == {"issue_locator"}
    description = schema["properties"]["issue_locator"]["description"]
    assert "owner/repo#number" in description
    assert "PROJ-123" in description
    assert "over a bare key" in description


_SENTINELS = ("SENTINEL-355-BODY", "SENTINEL-355-AC", "SENTINEL-355-URL")
_CONTENT = {
    "ticket_identifier": "KERN-355",
    "title": "Login",
    "body": "Users sign in with email. SENTINEL-355-BODY",
    "acceptance_criteria": "- Lockout after 5 failures SENTINEL-355-AC",
    "source_url": "https://tracker.example/SENTINEL-355-URL",
}


def _mcp_workflow(tmp_path: Path, **kwargs) -> tuple[McpTestDesignWorkflow, TestDesignFacade]:
    facade = build_fake_facade(tmp_path, **kwargs)
    return McpTestDesignWorkflow(McpTestDesignOperations(facade)), facade


def test_start_from_content_projects_client_supplied_origin(tmp_path: Path) -> None:
    reader = RecordingIssueReader()
    workflow, facade = _mcp_workflow(tmp_path, reader=reader)

    started = workflow.start_from_content(dict(_CONTENT))

    assert started["evidence_origin"] == "client_supplied"
    assert started["status"] == "coverage_review"
    assert started["version"] == 1
    assert started["ticket_identifier"] == "KERN-355"
    assert reader.calls == []
    stored = facade.get_draft(started["draft_id"])
    assert stored.conversation_id.startswith("mcp-")


def test_live_start_projects_live_origin(tmp_path: Path) -> None:
    workflow, _facade = _mcp_workflow(tmp_path)

    started = workflow.start({"issue_locator": ISSUE_LOCATOR})

    assert started["evidence_origin"] == "live"


def test_supplied_evidence_never_appears_in_mcp_outputs(tmp_path: Path) -> None:
    workflow, _facade = _mcp_workflow(tmp_path)

    started = workflow.start_from_content(dict(_CONTENT))
    draft_id = started["draft_id"]
    fetched = workflow.get({"draft_id": draft_id})
    confirmed = workflow.confirm(
        {
            "draft_id": draft_id,
            "expected_version": started["version"],
            "candidate_ids": ["cand-1", "cand-2"],
        }
    )
    generated = workflow.generate(
        {
            "draft_id": draft_id,
            "expected_version": confirmed["version"],
            "type_overrides": [
                {"candidate_id": "cand-1", "test_type": "manual"},
                {"candidate_id": "cand-2", "test_type": "cucumber"},
            ],
        }
    )
    exported = workflow.export_feature({"draft_id": draft_id})

    assert generated["generated_cases"]
    assert exported["scenario_count"] == 1
    for result in (started, fetched, confirmed, generated, exported):
        encoded = json.dumps(result)
        for sentinel in _SENTINELS:
            assert sentinel not in encoded
        assert "client_evidence_text" not in encoded
        assert result["evidence_origin"] == "client_supplied"


def test_unknown_draft_maps_to_target_not_found(tmp_path: Path) -> None:
    workflow, _facade = _workflow(tmp_path)

    with pytest.raises(ToolTargetNotFoundError):
        workflow.get(draft_id="missing-draft")


def test_disabled_pack_maps_to_unavailable(tmp_path: Path) -> None:
    workflow, _facade = _workflow(tmp_path, pack_on=False)

    with pytest.raises(ToolUnavailableError):
        workflow.get(draft_id="any")


def test_generate_follows_the_300_contract(tmp_path: Path) -> None:
    workflow, _facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)
    ready = workflow.confirm_selection(
        draft_id=started.draft_id,
        expected_version=started.version,
        candidate_ids=("cand-1", "cand-2"),
    )

    generated = workflow.generate(
        draft_id=ready.draft_id,
        expected_version=ready.version,
        candidate_ids=None,
        type_overrides=(("cand-1", "manual"), ("cand-2", "cucumber")),
        overwrite_edited=False,
    )

    assert generated.status == "case_editing"
    assert generated.version == ready.version + 1
    cases = {case.candidate_id: case for case in generated.generated_cases}
    assert cases["cand-1"].test_type == "manual"
    assert tuple(cases["cand-1"].steps) == (
        "Open the login page",
        "Submit valid credentials",
    )
    assert cases["cand-1"].gherkin == ""
    assert cases["cand-2"].test_type == "cucumber"
    assert cases["cand-2"].gherkin.startswith("Given a locked account")
    assert generated.cucumber_feature == "Login"
    assert generated.cucumber_background == "Given the login page is open"


def _capture_type_overrides(
    facade: TestDesignFacade, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[tuple[str, str], ...]]:
    captured: list[tuple[tuple[str, str], ...]] = []

    def _generate_cases(draft_id, request):
        captured.append(request.type_overrides)
        return facade.get_draft(draft_id)

    monkeypatch.setattr(facade, "generate_cases", _generate_cases)
    return captured


def test_generate_applies_one_test_type_to_every_selected_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)
    ready = workflow.confirm_selection(
        draft_id=started.draft_id,
        expected_version=started.version,
        candidate_ids=("cand-1", "cand-3"),
    )
    captured = _capture_type_overrides(facade, monkeypatch)

    workflow.generate(
        draft_id=ready.draft_id,
        expected_version=ready.version,
        candidate_ids=None,
        type_overrides=(),
        overwrite_edited=False,
        test_type="cucumber",
    )

    assert captured == [(("cand-1", "cucumber"), ("cand-3", "cucumber"))]


def test_generate_type_overrides_win_over_test_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)
    ready = workflow.confirm_selection(
        draft_id=started.draft_id,
        expected_version=started.version,
        candidate_ids=("cand-1", "cand-2", "cand-3"),
    )
    captured = _capture_type_overrides(facade, monkeypatch)

    workflow.generate(
        draft_id=ready.draft_id,
        expected_version=ready.version,
        candidate_ids=("cand-1", "cand-2"),
        type_overrides=(("cand-2", "manual"),),
        overwrite_edited=False,
        test_type="cucumber",
    )

    assert captured == [(("cand-1", "cucumber"), ("cand-2", "manual"))]


def test_generate_rejects_unselected_candidate_via_existing_contract(
    tmp_path: Path,
) -> None:
    workflow, _facade = _workflow(tmp_path)
    started = workflow.start(issue_locator=ISSUE_LOCATOR)
    ready = workflow.confirm_selection(
        draft_id=started.draft_id,
        expected_version=started.version,
        candidate_ids=("cand-1",),
    )

    with pytest.raises(ToolArgumentValidationError):
        workflow.generate(
            draft_id=ready.draft_id,
            expected_version=ready.version,
            candidate_ids=("cand-3",),
            type_overrides=(),
            overwrite_edited=False,
        )
