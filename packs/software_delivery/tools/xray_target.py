"""Tool adapter for ``software_delivery.xray_target`` (#397).

Read-only: reports the Jira project and instance Xray tests are created in and
what that project supports, after checking it through the importer's schema
discovery. Needs no approval.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from domain.errors import ConnectorAuthError, ConnectorUnavailableError, ToolFailureError
from domain.ports import XrayTestImporter
from domain.test_management.xray import XrayTestCreateSchema
from packs.software_delivery.errors import XrayExportValidationError
from packs.software_delivery.tools.xray_calls import MSG_XRAY_UNAVAILABLE

TOOL_NAME = "software_delivery.xray_target"
TOOL_DESCRIPTION = (
    "Show which Jira project and instance Kernector creates Xray tests in, and "
    "whether that project supports Manual, Cucumber and Scenario Outline tests and "
    "issue links. Takes no arguments and changes nothing. Call it before "
    "create_xray_tests_from_files or create_xray_tests so the user can confirm "
    "the destination; the project is set by the server's configuration."
)


class XrayTargetTool:
    """Implements ``domain.ports.Tool``; read-only, so never gated by approval."""

    def __init__(
        self,
        *,
        importer: XrayTestImporter,
        destination_label: str,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._importer = importer
        self._destination_label = destination_label
        self.args_schema = args_schema
        self.output_schema = output_schema

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        if not isinstance(arguments, Mapping) or arguments:
            raise XrayExportValidationError("this tool takes no arguments")
        schema = self._schema()
        return json.dumps(
            {
                "project_key": schema.project_key,
                "destination": self._destination_label,
                "supports_manual": schema.supports_manual,
                "supports_cucumber": schema.supports_cucumber,
                "supports_cucumber_outline": schema.supports_cucumber_outline,
                "supports_issue_link": schema.supports_issue_link,
            },
            separators=(",", ":"),
        )

    def _schema(self) -> XrayTestCreateSchema:
        try:
            return self._importer.schema()
        except ConnectorAuthError:
            raise
        except ConnectorUnavailableError as exc:
            raise ToolFailureError(MSG_XRAY_UNAVAILABLE) from exc
        except Exception as exc:  # noqa: BLE001 - missing project, permissions or bad metadata
            raise ToolFailureError(
                f"Could not reach the Xray project for {self._destination_label}"
            ) from exc
