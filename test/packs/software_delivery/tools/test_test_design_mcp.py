"""Tests for the Software Delivery Test Design MCP tools (#338)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from domain.errors import ToolArgumentValidationError
from packs.software_delivery.test_design.views import (
    GeneratedTestCaseView,
    SourceReferenceView,
    TestCandidateView,
    TestCoverageDraftView,
)
from packs.software_delivery.tools.test_design_mcp import (
    TOOL_CONFIRM,
    TOOL_GENERATE,
    TOOL_GET,
    TOOL_START,
    TestDesignConfirmTool,
    TestDesignGenerateTool,
    TestDesignGetTool,
    TestDesignStartTool,
)


def _draft(**overrides: object) -> TestCoverageDraftView:
    issue = SourceReferenceView(source_id="issue:I_node", source_type="github")
    draft = TestCoverageDraftView(
        draft_id="draft-1",
        workspace_id="ws-secret",
        conversation_id="conv-secret",
        source_reference=issue,
        ticket_identifier="acme/app#7",
        status="coverage_review",
        candidates=(
            TestCandidateView(
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                rationale="AC says so.",
                evidence_references=(issue,),
                selected=False,
                origin="suggested",
            ),
            TestCandidateView(
                candidate_id="cand-2",
                title="Manual addition",
                category="edge_case",
                rationale="User-authored.",
                evidence_references=(),
                selected=True,
                origin="manual",
                test_type="cucumber",
            ),
        ),
        version=1,
        selected_candidate_ids=("cand-2",),
        evidence_fingerprint="fp-secret",
    )
    return replace(draft, **overrides)


class _FakeWorkflow:
    def __init__(self, draft: TestCoverageDraftView | None = None) -> None:
        self.draft = draft if draft is not None else _draft()
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.error: Exception | None = None

    def _record(self, name: str, **kwargs: object) -> TestCoverageDraftView:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error
        return self.draft

    def start(self, *, issue_locator, conversation_id):
        return self._record(
            "start", issue_locator=issue_locator, conversation_id=conversation_id
        )

    def get(self, *, draft_id):
        return self._record("get", draft_id=draft_id)

    def confirm_selection(self, *, draft_id, expected_version, candidate_ids):
        return self._record(
            "confirm_selection",
            draft_id=draft_id,
            expected_version=expected_version,
            candidate_ids=candidate_ids,
        )

    def generate(
        self,
        *,
        draft_id,
        expected_version,
        candidate_ids,
        type_overrides,
        overwrite_edited,
    ):
        return self._record(
            "generate",
            draft_id=draft_id,
            expected_version=expected_version,
            candidate_ids=candidate_ids,
            type_overrides=type_overrides,
            overwrite_edited=overwrite_edited,
        )


def _run(tool_cls, workflow: _FakeWorkflow, arguments: dict[str, object]) -> dict:
    tool = tool_cls(lambda: workflow)
    return json.loads(tool.run(arguments))


def test_tool_ids_are_stable() -> None:
    assert TOOL_START == "software_delivery.test_design_start"
    assert TOOL_GET == "software_delivery.test_design_get"
    assert TOOL_CONFIRM == "software_delivery.test_design_confirm"
    assert TOOL_GENERATE == "software_delivery.test_design_generate"
    workflow = _FakeWorkflow()
    names = [
        cls(lambda: workflow).name
        for cls in (
            TestDesignStartTool,
            TestDesignGetTool,
            TestDesignConfirmTool,
            TestDesignGenerateTool,
        )
    ]
    assert names == [TOOL_START, TOOL_GET, TOOL_CONFIRM, TOOL_GENERATE]


def test_start_projects_only_mcp_safe_fields() -> None:
    workflow = _FakeWorkflow()

    payload = _run(TestDesignStartTool, workflow, {"issue_locator": "acme/app#7"})

    assert workflow.calls == [
        ("start", {"issue_locator": "acme/app#7", "conversation_id": None})
    ]
    assert payload["draft_id"] == "draft-1"
    assert payload["ticket_identifier"] == "acme/app#7"
    assert payload["status"] == "coverage_review"
    assert payload["version"] == 1
    assert payload["selected_candidate_ids"] == ["cand-2"]
    assert payload["candidates"][0]["evidence_references"] == [
        {"source_id": "issue:I_node", "source_type": "github"}
    ]
    encoded = json.dumps(payload)
    for leaked in ("ws-secret", "conv-secret", "fp-secret"):
        assert leaked not in encoded
    for key in (
        "workspace_id",
        "conversation_id",
        "evidence_fingerprint",
        "source_reference",
    ):
        assert key not in payload


def test_trust_marker_covers_model_generated_content_only() -> None:
    workflow = _FakeWorkflow(
        _draft(
            status="case_editing",
            generated_cases=(
                GeneratedTestCaseView(
                    candidate_id="cand-2",
                    test_type="cucumber",
                    automation_fit="applicable",
                    automation_rationale="UI flow.",
                    availability="available",
                    preconditions="",
                    steps=(),
                    expected_result="",
                    gherkin="Given a user\nWhen they log in\nThen it works",
                    user_edited=False,
                ),
            ),
            cucumber_feature="Login",
            cucumber_background="Given the app is up",
        )
    )

    payload = _run(TestDesignGetTool, workflow, {"draft_id": "draft-1"})

    suggested, manual = payload["candidates"]
    assert suggested["untrusted_model_output"] is True
    assert manual["untrusted_model_output"] is False
    assert payload["generated_cases"][0]["untrusted_model_output"] is True
    assert payload["generated_cases"][0]["gherkin"].startswith("Given a user")
    assert payload["cucumber"] == {
        "feature": "Login",
        "background": "Given the app is up",
        "untrusted_model_output": True,
    }
    assert "untrusted_model_output" not in payload


@pytest.mark.parametrize(
    ("tool_cls", "arguments"),
    [
        (TestDesignStartTool, {"issue_locator": "acme/app#7", "workspace_id": "x"}),
        (TestDesignGetTool, {"draft_id": "d", "workspace_id": "x"}),
        (
            TestDesignConfirmTool,
            {
                "draft_id": "d",
                "expected_version": 1,
                "candidate_ids": ["c"],
                "workspace_id": "x",
            },
        ),
        (
            TestDesignGenerateTool,
            {"draft_id": "d", "expected_version": 1, "workspace_id": "x"},
        ),
        (TestDesignGetTool, {"draft_id": "d", "unexpected": True}),
        (TestDesignGetTool, {}),
        (TestDesignStartTool, {"issue_locator": "  "}),
        (TestDesignConfirmTool, {"draft_id": "d", "expected_version": 1, "candidate_ids": []}),
        (TestDesignConfirmTool, {"draft_id": "d", "expected_version": 0, "candidate_ids": ["c"]}),
        (TestDesignConfirmTool, {"draft_id": "d", "expected_version": True, "candidate_ids": ["c"]}),
        (
            TestDesignGenerateTool,
            {
                "draft_id": "d",
                "expected_version": 1,
                "type_overrides": [{"candidate_id": "c", "test_type": "robot"}],
            },
        ),
    ],
)
def test_invalid_arguments_are_rejected_before_workflow(tool_cls, arguments) -> None:
    workflow = _FakeWorkflow()
    tool = tool_cls(lambda: workflow)

    with pytest.raises(ToolArgumentValidationError):
        tool.run(arguments)

    assert workflow.calls == []


def test_schemas_never_expose_workspace_id() -> None:
    workflow = _FakeWorkflow()
    for cls in (
        TestDesignStartTool,
        TestDesignGetTool,
        TestDesignConfirmTool,
        TestDesignGenerateTool,
    ):
        tool = cls(lambda: workflow)
        assert "workspace_id" not in json.dumps(tool.args_schema.model_json_schema())
        assert "workspace_id" not in json.dumps(tool.output_schema.model_json_schema())
        assert tool.args_schema.model_json_schema().get("additionalProperties") is False


def test_confirm_forwards_selection_and_version() -> None:
    workflow = _FakeWorkflow()

    _run(
        TestDesignConfirmTool,
        workflow,
        {"draft_id": "draft-1", "expected_version": 3, "candidate_ids": ["cand-1"]},
    )

    assert workflow.calls == [
        (
            "confirm_selection",
            {
                "draft_id": "draft-1",
                "expected_version": 3,
                "candidate_ids": ("cand-1",),
            },
        )
    ]


def test_generate_forwards_the_300_request_shape() -> None:
    workflow = _FakeWorkflow()

    _run(
        TestDesignGenerateTool,
        workflow,
        {
            "draft_id": "draft-1",
            "expected_version": 4,
            "candidate_ids": ["cand-1"],
            "type_overrides": [{"candidate_id": "cand-1", "test_type": "manual"}],
            "overwrite_edited": True,
        },
    )
    _run(
        TestDesignGenerateTool,
        workflow,
        {"draft_id": "draft-1", "expected_version": 5},
    )

    assert workflow.calls == [
        (
            "generate",
            {
                "draft_id": "draft-1",
                "expected_version": 4,
                "candidate_ids": ("cand-1",),
                "type_overrides": (("cand-1", "manual"),),
                "overwrite_edited": True,
            },
        ),
        (
            "generate",
            {
                "draft_id": "draft-1",
                "expected_version": 5,
                "candidate_ids": None,
                "type_overrides": (),
                "overwrite_edited": False,
            },
        ),
    ]


def test_generate_returns_skipped_edited_ids() -> None:
    workflow = _FakeWorkflow(_draft(skipped_edited_candidate_ids=("cand-2",)))

    payload = _run(
        TestDesignGenerateTool, workflow, {"draft_id": "draft-1", "expected_version": 2}
    )

    assert payload["skipped_edited_candidate_ids"] == ["cand-2"]


def test_workflow_errors_propagate_unchanged() -> None:
    class _Boom(RuntimeError):
        pass

    workflow = _FakeWorkflow()
    error = _Boom("internal detail")
    workflow.error = error
    tool = TestDesignGetTool(lambda: workflow)

    with pytest.raises(_Boom) as caught:
        tool.run({"draft_id": "draft-1"})

    assert caught.value is error


def test_workflow_factory_is_called_per_invocation() -> None:
    created: list[_FakeWorkflow] = []

    def factory() -> _FakeWorkflow:
        workflow = _FakeWorkflow()
        created.append(workflow)
        return workflow

    tool = TestDesignGetTool(factory)
    assert created == []
    tool.run({"draft_id": "draft-1"})
    tool.run({"draft_id": "draft-1"})

    assert len(created) == 2
