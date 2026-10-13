"""software_delivery.xray_target: read-only check of where Xray tests go (#397)."""

from __future__ import annotations

import json

import pytest

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorUnavailableError,
    ToolFailureError,
)
from domain.test_management.xray import XrayTestCreateSchema
from domain.tool_approval import ToolApprovalPolicy
from packs.software_delivery.errors import XrayExportValidationError
from packs.software_delivery.tools.create_xray_tests import (
    TOOL_DESCRIPTION as CREATE_FROM_DRAFT_DESCRIPTION,
)
from packs.software_delivery.tools.test_design_mcp import TestDesignStartFromContentTool
from packs.software_delivery.tools.xray_target import TOOL_NAME, XrayTargetTool

LABEL = "Jira project QA on jira.example.test"


class _Importer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def schema(self) -> XrayTestCreateSchema:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return XrayTestCreateSchema("QA", True, False, True, supports_cucumber_outline=False)


def _tool(importer: _Importer) -> XrayTargetTool:
    return XrayTargetTool(importer=importer, destination_label=LABEL)


def test_reports_the_checked_project_and_what_it_supports() -> None:
    importer = _Importer()

    payload = json.loads(_tool(importer).run({}))

    assert payload == {
        "project_key": "QA",
        "destination": LABEL,
        "supports_manual": True,
        "supports_cucumber": False,
        "supports_cucumber_outline": False,
        "supports_issue_link": True,
    }
    assert importer.calls == 1


def test_needs_no_approval() -> None:
    assert ToolApprovalPolicy().requires_approval(TOOL_NAME) is False


def test_description_says_when_to_use_it() -> None:
    description = _tool(_Importer()).description

    assert "before" in description and "create_xray_tests_from_files" in description


@pytest.mark.parametrize(
    "description",
    [CREATE_FROM_DRAFT_DESCRIPTION, TestDesignStartFromContentTool._description],
)
def test_draft_tools_point_existing_test_files_to_the_file_tool(description: str) -> None:
    assert ".feature" in description and "create_xray_tests_from_files" in description


@pytest.mark.parametrize("arguments", [{"project_key": "QA"}, "nope"])
def test_takes_no_arguments(arguments: object) -> None:
    with pytest.raises(XrayExportValidationError):
        _tool(_Importer()).run(arguments)  # type: ignore[arg-type]


def test_auth_failures_propagate() -> None:
    with pytest.raises(ConnectorAuthError):
        _tool(_Importer(ConnectorAuthError("x"))).run({})


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ConnectorUnavailableError("x"), "Xray is temporarily unavailable"),
        (ConnectorError("x"), f"Could not reach the Xray project for {LABEL}"),
    ],
)
def test_other_failures_name_the_destination_without_details(
    error: Exception, message: str
) -> None:
    with pytest.raises(ToolFailureError) as caught:
        _tool(_Importer(error)).run({})

    assert str(caught.value) == message
