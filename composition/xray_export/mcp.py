"""MCP schemas and workspace binding for Xray test creation (#199, ADR 0010).

Composition owns the strict MCP argument and result schemas so the pack stays
free of pydantic; the binding is workspace-bound through the draft loader.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from domain.ports import XrayTestImporter
    from infrastructure.config import Settings


class CreateXrayTestsArgs(BaseModel):
    """Arguments for ``software_delivery.create_xray_tests`` on MCP."""

    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(
        min_length=1,
        max_length=128,
        description="Test Design draft id whose selected, generated cases become Xray tests.",
    )
    link_source_issue: bool = Field(
        default=True,
        description="Link each created test to the draft's Jira issue when possible.",
    )


class CreateXrayTestsResult(BaseModel):
    """Safe receipt: created issue keys and counts only."""

    model_config = ConfigDict(extra="forbid")

    created_keys: list[str]
    created_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class XrayMcpBinding:
    """Collaborators for the pack's ``build_mcp_tools(xray_binding=...)``."""

    importer: XrayTestImporter
    load_draft: Callable[[str], object]
    project_key: str
    args_schema: type = field(default=CreateXrayTestsArgs)
    output_schema: type = field(default=CreateXrayTestsResult)


def build_mcp_xray_binding(settings: Settings) -> XrayMcpBinding | None:
    """Return the workspace-bound binding, or None when Xray is not configured."""
    from composition.container import _xray_tool_collaborators

    importer, load_draft = _xray_tool_collaborators(settings)
    if importer is None or load_draft is None:
        return None
    return XrayMcpBinding(
        importer=importer,
        load_draft=load_draft,
        project_key=settings.xray.project_key or "",
    )
