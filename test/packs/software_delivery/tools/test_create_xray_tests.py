"""Seam: ``CreateXrayTestsTool.run`` with a fake draft loader and importer (#199)."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorUnavailableError,
    ToolFailureError,
)
from domain.knowledge import SourceReference
from domain.test_management.xray import (
    XrayImportResult,
    XrayRequiredFieldsError,
    XrayTestCreateSchema,
    XrayTestSpec,
    XrayTestStep,
)
from packs.software_delivery.errors import XrayExportValidationError
from packs.software_delivery.test_design.models import (
    GeneratedTestCase,
    TestCandidate,
    TestCoverageDraft,
)
from packs.software_delivery.tools.create_xray_tests import CreateXrayTestsTool


class _FakeImporter:
    def __init__(
        self,
        *,
        schema: XrayTestCreateSchema | None = None,
        result: XrayImportResult | None = None,
        error: Exception | None = None,
        schema_error: Exception | None = None,
    ) -> None:
        self.schema_error = schema_error
        self.schema_value = schema or XrayTestCreateSchema(
            project_key="QA",
            supports_manual=True,
            supports_cucumber=True,
            supports_issue_link=True,
        )
        self.result = result or XrayImportResult(created_keys=("QA-1",), failed_count=0)
        self.error = error
        self.calls: list[tuple[XrayTestSpec, ...]] = []

    def schema(self) -> XrayTestCreateSchema:
        if self.schema_error is not None:
            raise self.schema_error
        return self.schema_value

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        self.calls.append(tuple(specs))
        if self.error is not None:
            raise self.error
        return self.result


def _candidate(candidate_id: str = "cand-1", **overrides: object) -> TestCandidate:
    base: dict[str, object] = {
        "candidate_id": candidate_id,
        "title": "Valid login",
        "category": "positive",
        "rationale": "Core happy path.",
        "evidence_references": (SourceReference("PROJ-42", "jira"),),
        "selected": True,
        "origin": "suggested",
        "test_type": "manual",
    }
    base.update(overrides)
    return TestCandidate(**base)  # type: ignore[arg-type]


def _manual_case(candidate_id: str = "cand-1", **overrides: object) -> GeneratedTestCase:
    base: dict[str, object] = {
        "candidate_id": candidate_id,
        "test_type": "manual",
        "automation_fit": "applicable",
        "automation_rationale": "",
        "availability": "available",
        "preconditions": "User exists",
        "steps": ("Open login page", "Submit valid credentials"),
        "expected_result": "Dashboard is shown",
        "gherkin": "",
        "user_edited": False,
    }
    base.update(overrides)
    return GeneratedTestCase(**base)  # type: ignore[arg-type]


def _cucumber_case(candidate_id: str = "cand-2", **overrides: object) -> GeneratedTestCase:
    base: dict[str, object] = {
        "candidate_id": candidate_id,
        "test_type": "cucumber",
        "automation_fit": "applicable",
        "automation_rationale": "",
        "availability": "available",
        "preconditions": "",
        "steps": (),
        "expected_result": "",
        "gherkin": "When I log in\nThen I see the dashboard",
        "user_edited": False,
    }
    base.update(overrides)
    return GeneratedTestCase(**base)  # type: ignore[arg-type]


def _draft(
    *,
    candidates: Sequence[TestCandidate] | None = None,
    cases: Sequence[GeneratedTestCase] | None = None,
    **overrides: object,
) -> TestCoverageDraft:
    base: dict[str, object] = {
        "draft_id": "draft-1",
        "workspace_id": "ws-1",
        "conversation_id": "conv-1",
        "source_reference": SourceReference("PROJ-42", "jira"),
        "ticket_identifier": "PROJ-42",
        "source_provider": "jira",
        "status": "case_editing",
        "candidates": tuple(candidates) if candidates is not None else (_candidate(),),
        "version": 1,
        "generated_cases": tuple(cases) if cases is not None else (_manual_case(),),
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def _tool(
    importer: _FakeImporter, draft: TestCoverageDraft | None = None
) -> CreateXrayTestsTool:
    drafts = {} if draft is None else {draft.draft_id: draft}
    return CreateXrayTestsTool(load_draft=drafts.get, importer=importer)


def test_manual_case_is_created_and_returns_safe_summary() -> None:
    importer = _FakeImporter(
        result=XrayImportResult(created_keys=("QA-7",), failed_count=0)
    )
    tool = _tool(importer, _draft())

    result = tool.run({"draft_id": "draft-1", "link_source_issue": False})

    assert json.loads(result) == {
        "created_keys": ["QA-7"],
        "created_count": 1,
        "failed_count": 0,
    }
    assert importer.calls == [
        (
            XrayTestSpec(
                title="Valid login",
                kind="manual",
                preconditions="User exists",
                steps=(
                    XrayTestStep(action="Open login page"),
                    XrayTestStep(
                        action="Submit valid credentials",
                        expected="Dashboard is shown",
                    ),
                ),
                source_issue_key="PROJ-42",
            ),
        )
    ]


def test_cucumber_case_carries_shared_background_then_scenario_steps() -> None:
    importer = _FakeImporter()
    draft = _draft(
        candidates=(
            _candidate("cand-2", title="Login via SSO", test_type="cucumber"),
        ),
        cases=(_cucumber_case("cand-2"),),
        cucumber_feature="Login",
        cucumber_background="Given the app is open",
    )

    _tool(importer, draft).run({"draft_id": "draft-1", "link_source_issue": False})

    assert importer.calls == [
        (
            XrayTestSpec(
                title="Login via SSO",
                kind="cucumber",
                gherkin=(
                    "Given the app is open\nWhen I log in\nThen I see the dashboard"
                ),
                source_issue_key="PROJ-42",
            ),
        )
    ]


def test_insufficient_and_unselected_candidates_are_not_created() -> None:
    importer = _FakeImporter()
    draft = _draft(
        candidates=(
            _candidate("cand-1"),
            _candidate("cand-2", title="Locked account"),
            _candidate("cand-3", title="Remember me", selected=False),
        ),
        cases=(
            _manual_case("cand-1"),
            _manual_case(
                "cand-2",
                availability="insufficient_evidence",
                preconditions="",
                steps=(),
                expected_result="",
            ),
        ),
    )

    _tool(importer, draft).run({"draft_id": "draft-1", "link_source_issue": False})

    assert [spec.title for spec in importer.calls[0]] == ["Valid login"]


_NOTHING_TO_CREATE = _draft(
    cases=(
        _manual_case(
            availability="insufficient_evidence",
            preconditions="",
            steps=(),
            expected_result="",
        ),
    ),
)


@pytest.mark.parametrize(
    "draft",
    [None, _NOTHING_TO_CREATE],
    ids=["draft_not_found", "no_available_cases"],
)
def test_missing_draft_or_no_available_cases_is_rejected_before_import(
    draft: TestCoverageDraft | None,
) -> None:
    importer = _FakeImporter()

    with pytest.raises(XrayExportValidationError):
        _tool(importer, draft).run({"draft_id": "draft-1"})

    assert importer.calls == []


@pytest.mark.parametrize(
    "arguments,draft_overrides,expected",
    [
        ({"draft_id": "draft-1"}, {}, "PROJ-42"),
        ({"draft_id": "draft-1", "link_source_issue": True}, {}, "PROJ-42"),
        ({"draft_id": "draft-1", "link_source_issue": False}, {}, None),
        (
            {"draft_id": "draft-1"},
            {"source_provider": "github", "ticket_identifier": "acme/web#12"},
            None,
        ),
    ],
    ids=["default_links_jira", "explicit_link", "link_disabled", "non_jira_source"],
)
def test_source_issue_link_only_for_jira_sources(
    arguments: dict[str, object],
    draft_overrides: dict[str, object],
    expected: str | None,
) -> None:
    importer = _FakeImporter()

    _tool(importer, _draft(**draft_overrides)).run(arguments)

    assert [spec.link_issue_key for spec in importer.calls[0]] == [expected]


@pytest.mark.parametrize(
    "arguments,draft_overrides,expected",
    [
        ({"draft_id": "draft-1", "link_source_issue": False}, {}, "PROJ-42"),
        (
            {"draft_id": "draft-1"},
            {"source_provider": "github", "ticket_identifier": "acme/web#12"},
            None,
        ),
    ],
    ids=["jira_source_without_link", "non_jira_source"],
)
def test_jira_source_issue_is_passed_for_field_inheritance_even_without_a_link(
    arguments: dict[str, object],
    draft_overrides: dict[str, object],
    expected: str | None,
) -> None:
    importer = _FakeImporter()

    _tool(importer, _draft(**draft_overrides)).run(arguments)

    assert [spec.source_issue_key for spec in importer.calls[0]] == [expected]


def test_required_jira_fields_xray_cannot_fill_are_named_in_the_failure() -> None:
    importer = _FakeImporter(error=XrayRequiredFieldsError(("Component/s", "Fix Version/s")))

    with pytest.raises(ToolFailureError) as caught:
        _tool(importer, _draft()).run({"draft_id": "draft-1"})

    assert "Component/s" in str(caught.value)
    assert "Fix Version/s" in str(caught.value)


def _schema(**overrides: bool) -> XrayTestCreateSchema:
    base = {
        "supports_manual": True,
        "supports_cucumber": True,
        "supports_issue_link": True,
    }
    base.update(overrides)
    return XrayTestCreateSchema(project_key="QA", **base)


_CUCUMBER_DRAFT = _draft(
    candidates=(_candidate("cand-2", test_type="cucumber"),),
    cases=(_cucumber_case("cand-2"),),
)


@pytest.mark.parametrize(
    "schema,draft,arguments",
    [
        (_schema(supports_manual=False), _draft(), {"draft_id": "draft-1"}),
        (_schema(supports_cucumber=False), _CUCUMBER_DRAFT, {"draft_id": "draft-1"}),
        (_schema(supports_issue_link=False), _draft(), {"draft_id": "draft-1"}),
    ],
    ids=["manual_unsupported", "cucumber_unsupported", "link_unsupported"],
)
def test_missing_project_capability_fails_before_any_create(
    schema: XrayTestCreateSchema,
    draft: TestCoverageDraft,
    arguments: dict[str, object],
) -> None:
    importer = _FakeImporter(schema=schema)

    with pytest.raises(ToolFailureError):
        _tool(importer, draft).run(arguments)

    assert importer.calls == []


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"draft_id": ""},
        {"draft_id": "   "},
        {"draft_id": 7},
        {"draft_id": "draft-1", "link_source_issue": "yes"},
        {"draft_id": "draft-1", "cases": []},
        {"draft_id": "draft-1", "project_key": "OTHER"},
    ],
    ids=[
        "missing_draft_id",
        "empty_draft_id",
        "blank_draft_id",
        "non_string_draft_id",
        "non_bool_link",
        "unknown_cases_key",
        "unknown_project_key",
    ],
)
def test_invalid_arguments_are_rejected_before_any_lookup(
    arguments: dict[str, object],
) -> None:
    importer = _FakeImporter()
    lookups: list[str] = []

    def load_draft(draft_id: str) -> TestCoverageDraft | None:
        lookups.append(draft_id)
        return _draft()

    tool = CreateXrayTestsTool(load_draft=load_draft, importer=importer)

    with pytest.raises(XrayExportValidationError):
        tool.run(arguments)

    assert lookups == []
    assert importer.calls == []


_SECRET = "Bearer xray-secret-token customfield_10100"


@pytest.mark.parametrize("stage", ["schema", "import"])
def test_auth_error_passes_through_unchanged(stage: str) -> None:
    error = ConnectorAuthError("rejected")
    importer = (
        _FakeImporter(schema_error=error)
        if stage == "schema"
        else _FakeImporter(error=error)
    )

    with pytest.raises(ConnectorAuthError) as caught:
        _tool(importer, _draft()).run({"draft_id": "draft-1"})

    assert caught.value is error


@pytest.mark.parametrize("stage", ["schema", "import"])
@pytest.mark.parametrize(
    "error",
    [
        ConnectorUnavailableError(_SECRET),
        ConnectorError(_SECRET),
        RuntimeError(_SECRET),
    ],
    ids=["unavailable", "connector", "unexpected"],
)
def test_other_failures_become_sanitized_tool_failures(
    stage: str, error: Exception
) -> None:
    importer = (
        _FakeImporter(schema_error=error)
        if stage == "schema"
        else _FakeImporter(error=error)
    )

    with pytest.raises(ToolFailureError) as caught:
        _tool(importer, _draft()).run({"draft_id": "draft-1"})

    assert caught.value.__cause__ is error
    assert "secret" not in str(caught.value)
    assert "customfield" not in str(caught.value)


def test_nothing_created_is_a_tool_failure() -> None:
    importer = _FakeImporter(
        result=XrayImportResult(created_keys=(), failed_count=1)
    )

    with pytest.raises(ToolFailureError):
        _tool(importer, _draft()).run({"draft_id": "draft-1"})


def test_partial_create_reports_created_keys_and_failed_count() -> None:
    draft = _draft(
        candidates=(_candidate("cand-1"), _candidate("cand-2", title="Locked")),
        cases=(_manual_case("cand-1"), _manual_case("cand-2")),
    )
    importer = _FakeImporter(
        result=XrayImportResult(created_keys=("QA-3",), failed_count=1)
    )

    result = _tool(importer, draft).run({"draft_id": "draft-1"})

    assert json.loads(result) == {
        "created_keys": ["QA-3"],
        "created_count": 1,
        "failed_count": 1,
    }


def test_link_capability_is_not_needed_when_linking_is_disabled() -> None:
    importer = _FakeImporter(schema=_schema(supports_issue_link=False))

    _tool(importer, _draft()).run({"draft_id": "draft-1", "link_source_issue": False})

    assert len(importer.calls) == 1
