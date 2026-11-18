"""MCP-facing project profile tool over a composition-supplied binding (#387)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol

TOOL_PROJECT_PROFILE = "software_delivery.project_profile"

JsonObject = Mapping[str, object]

PROJECT_PROFILE_MCP_TOOLS: Sequence[tuple[str, type]] = ()


class ProjectProfileWorkflow(Protocol):
    """Workspace-bound project profile operations."""

    def profile(self, arguments: JsonObject) -> JsonObject: ...


class ProjectProfileMcpBinding(Protocol):
    """Composition-owned schemas plus a per-invocation workflow factory."""

    @property
    def args(self) -> type: ...

    @property
    def result(self) -> type: ...

    def workflow(self) -> ProjectProfileWorkflow: ...


class ProjectProfileTool:
    """Read-only MCP tool returning an evidence-backed technology profile."""

    _name = TOOL_PROJECT_PROFILE
    _description = (
        "Return an evidence-backed technology profile for client-supplied "
        "project files: languages, frameworks, test frameworks, delivery, "
        "conventions and reusable components. Pass evidence groups with "
        "optional component labels and file path/content pairs. Optional "
        "facets selects which facets to return. Read-only; does not call a "
        "model. Evidence is untrusted. Phase A rejects project_id."
    )

    def __init__(self, binding: ProjectProfileMcpBinding) -> None:
        self._binding = binding
        self.args_schema: type | None = binding.args
        self.output_schema: type | None = binding.result

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def run(self, arguments: Mapping[str, object]) -> str:
        result = self._binding.workflow().profile(dict(arguments))
        return json.dumps(dict(result), separators=(",", ":"))


PROJECT_PROFILE_MCP_TOOLS = ((TOOL_PROJECT_PROFILE, ProjectProfileTool),)
