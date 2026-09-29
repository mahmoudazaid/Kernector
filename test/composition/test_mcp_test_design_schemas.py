"""Composition-owned Test Design MCP schemas, validation, and projection (#338)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from composition.mcp_test_design import (
    McpTestDesignBinding,
    McpTestDesignWorkflow,
    TestDesignConfirmArgs,
    TestDesignDraftResult,
    TestDesignGenerateArgs,
    TestDesignGetArgs,
    TestDesignStartArgs,
)
from composition.test_design import (
    GeneratedTestCaseView,
    SourceReferenceView,
    TestCandidateView,
    TestCoverageDraftView,
)
from domain.errors import ToolArgumentValidationError
from packs.software_delivery.test_design.limits import (
    MAX_CANDIDATES,
    MAX_GENERATE_CANDIDATES,
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


class _FakeOperations:
    def __init__(self, draft: TestCoverageDraftView | None = None) -> None:
        self.draft = draft if draft is not None else _draft()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _record(self, name: str, **kwargs: object) -> TestCoverageDraftView:
        self.calls.append((name, kwargs))
        return self.draft

    def start(self, *, issue_locator):
        return self._record("start", issue_locator=issue_locator)

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


def _workflow(
    draft: TestCoverageDraftView | None = None,
) -> tuple[McpTestDesignWorkflow, _FakeOperations]:
    operations = _FakeOperations(draft)
    return McpTestDesignWorkflow(operations), operations  # type: ignore[arg-type]


def _ids(count: int) -> list[str]:
    return [f"cand-{index}" for index in range(count)]


def test_start_projects_only_mcp_safe_fields() -> None:
    workflow, operations = _workflow()

    payload = workflow.start({"issue_locator": " acme/app#7 "})

    assert operations.calls == [("start", {"issue_locator": "acme/app#7"})]
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
    workflow, _operations = _workflow(
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

    payload = workflow.get({"draft_id": "draft-1"})

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
    ("operation", "arguments"),
    [
        ("start", {"issue_locator": "acme/app#7", "workspace_id": "x"}),
        ("start", {"issue_locator": "acme/app#7", "conversation_id": "conv-1"}),
        ("get", {"draft_id": "d", "workspace_id": "x"}),
        (
            "confirm",
            {
                "draft_id": "d",
                "expected_version": 1,
                "candidate_ids": ["c"],
                "workspace_id": "x",
            },
        ),
        ("generate", {"draft_id": "d", "expected_version": 1, "workspace_id": "x"}),
        ("get", {"draft_id": "d", "unexpected": True}),
        ("get", {}),
        ("start", {"issue_locator": "  "}),
        ("confirm", {"draft_id": "d", "expected_version": 1, "candidate_ids": []}),
        (
            "confirm",
            {
                "draft_id": "d",
                "expected_version": 1,
                "candidate_ids": _ids(MAX_CANDIDATES + 1),
            },
        ),
        ("confirm", {"draft_id": "d", "expected_version": 0, "candidate_ids": ["c"]}),
        (
            "confirm",
            {"draft_id": "d", "expected_version": True, "candidate_ids": ["c"]},
        ),
        (
            "generate",
            {
                "draft_id": "d",
                "expected_version": 1,
                "candidate_ids": _ids(MAX_GENERATE_CANDIDATES + 1),
            },
        ),
        (
            "generate",
            {
                "draft_id": "d",
                "expected_version": 1,
                "type_overrides": [{"candidate_id": "c", "test_type": "robot"}],
            },
        ),
    ],
)
def test_invalid_arguments_are_rejected_before_operations(
    operation: str, arguments: dict[str, object]
) -> None:
    workflow, operations = _workflow()

    with pytest.raises(ToolArgumentValidationError):
        getattr(workflow, operation)(arguments)

    assert operations.calls == []


def test_confirm_accepts_every_candidate_a_draft_can_hold() -> None:
    workflow, operations = _workflow()
    candidate_ids = _ids(MAX_CANDIDATES)

    workflow.confirm(
        {"draft_id": "draft-1", "expected_version": 1, "candidate_ids": candidate_ids}
    )

    assert operations.calls[0][1]["candidate_ids"] == tuple(candidate_ids)


def test_schemas_never_expose_workspace_or_conversation_id() -> None:
    binding = McpTestDesignBinding(lambda: None)  # type: ignore[arg-type,return-value]
    for model in (
        binding.start_args,
        binding.get_args,
        binding.confirm_args,
        binding.generate_args,
    ):
        schema = model.model_json_schema()
        encoded = json.dumps(schema)
        assert "workspace_id" not in encoded
        assert "conversation_id" not in encoded
        assert schema.get("additionalProperties") is False
    result_schema = json.dumps(binding.result.model_json_schema())
    assert "workspace_id" not in result_schema
    assert "conversation_id" not in result_schema


def test_binding_exposes_composition_schemas() -> None:
    binding = McpTestDesignBinding(lambda: None)  # type: ignore[arg-type,return-value]

    assert binding.start_args is TestDesignStartArgs
    assert binding.get_args is TestDesignGetArgs
    assert binding.confirm_args is TestDesignConfirmArgs
    assert binding.generate_args is TestDesignGenerateArgs
    assert binding.result is TestDesignDraftResult


def test_confirm_forwards_selection_and_version() -> None:
    workflow, operations = _workflow()

    workflow.confirm(
        {"draft_id": "draft-1", "expected_version": 3, "candidate_ids": ["cand-1"]}
    )

    assert operations.calls == [
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
    workflow, operations = _workflow()

    workflow.generate(
        {
            "draft_id": "draft-1",
            "expected_version": 4,
            "candidate_ids": ["cand-1"],
            "type_overrides": [{"candidate_id": "cand-1", "test_type": "manual"}],
            "overwrite_edited": True,
        }
    )
    workflow.generate({"draft_id": "draft-1", "expected_version": 5})

    assert operations.calls == [
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
    workflow, _operations = _workflow(_draft(skipped_edited_candidate_ids=("cand-2",)))

    payload = workflow.generate({"draft_id": "draft-1", "expected_version": 2})

    assert payload["skipped_edited_candidate_ids"] == ["cand-2"]
