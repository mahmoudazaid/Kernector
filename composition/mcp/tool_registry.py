"""Composition-owned MCP tool registry with atomic authorization."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from composition.mcp.access import McpAccessPolicy, McpCallerContext
from domain.errors import (
    ToolArgumentValidationError,
    ToolEvidenceChangedError,
    ToolFailureError,
    ToolInsufficientEvidenceError,
    ToolSourceNotConnectedError,
    ToolSourceProviderMismatchError,
    ToolTargetNotFoundError,
    ToolUnavailableError,
    ToolUnsupportedSourceError,
    ToolVersionConflictError,
)
from domain.ports import Tool
from domain.tool_approval import (
    PendingToolApproval,
    ToolApprovalPolicy,
    project_pending_approval,
)

logger = logging.getLogger(__name__)

TOOL_UNAVAILABLE_CODE = "tool_unavailable"
GENERIC_ERROR_CODE = "internal_error"
VALIDATION_ERROR_CODE = "validation_error"
APPROVAL_REQUIRED_CODE = "approval_required"
APPROVAL_DECLINED_CODE = "approval_declined"
# A tool may set an optional ``approval_hints(arguments)`` method (not on the
# ``Tool`` port) returning ``ApprovalHints`` for the approval prompt. It only
# runs for tools the approval policy lists (ADR 0010).

# Presentation-owned approval gate: returns True only on explicit approval.
McpApprovalGate = Callable[[PendingToolApproval], bool]
# An args schema may raise ``PydanticCustomError(SAFE_VALIDATION_ERROR_TYPE,
# message)`` with a fixed message that never interpolates input; only that
# message replaces the generic validation text.
SAFE_VALIDATION_ERROR_TYPE = "mcp_safe_validation"
# A tool may set an optional ``failure_hints`` attribute (MCP-only, not on the
# ``Tool`` port) mapping a safe wire code to ``(required_tool_id, hint)``. The
# fixed hint is added only when that tool is contributed and effective for the
# caller, so it never reveals tools the caller cannot use.

# Exact exception type -> (wire code, fixed message). Only these escape.
_SAFE_FAILURES: Mapping[type[ToolFailureError], tuple[str, str]] = {
    ToolTargetNotFoundError: ("not_found", "Resource not found"),
    ToolVersionConflictError: (
        "version_conflict",
        "Version conflict; re-read and retry",
    ),
    ToolEvidenceChangedError: (
        "evidence_changed",
        "Source evidence changed; restart the workflow",
    ),
    ToolSourceNotConnectedError: (
        "source_not_connected",
        "Source is not connected",
    ),
    ToolInsufficientEvidenceError: (
        "insufficient_evidence",
        "No usable grounded evidence",
    ),
    ToolUnsupportedSourceError: (
        "unsupported_source",
        "No connected source accepts this locator",
    ),
    ToolSourceProviderMismatchError: (
        VALIDATION_ERROR_CODE,
        "Another connected provider accepts this locator; retry with that provider",
    ),
}

# Deprecated wire codes still sent as ``legacy_code`` for one release (#351).
_LEGACY_CODE_ALIASES: Mapping[str, str] = {
    "source_not_connected": "github_not_connected",
}

ToolFactory = Callable[[], Tool]


def mcp_tool_name(tool_id: str) -> str:
    """Return the advertised MCP name for *tool_id*.

    Clients such as Cursor rewrite dots in tool names and then call the
    rewritten name, so the wire name must already avoid them.

    Args:
        tool_id: Dotted registry id (e.g. ``software_delivery.test_design_start``).

    Returns:
        The id with dots replaced by underscores.
    """
    return tool_id.replace(".", "_")


@dataclass(frozen=True, slots=True)
class McpToolDescriptor:
    """Wire-ready tool metadata for ``tools/list`` (no mcp SDK types)."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class McpInvokeResult:
    """Sanitized invoke outcome for presentation to map to CallToolResult."""

    is_error: bool
    text: str
    code: str | None = None
    structured: Mapping[str, Any] | None = None


def _tool_unavailable() -> McpInvokeResult:
    payload = {"code": TOOL_UNAVAILABLE_CODE, "message": "Tool unavailable"}
    return McpInvokeResult(
        is_error=True,
        text=json.dumps(payload, separators=(",", ":")),
        code=TOOL_UNAVAILABLE_CODE,
        structured=payload,
    )


def _validation_error(message: str = "Invalid tool arguments") -> McpInvokeResult:
    payload = {"code": VALIDATION_ERROR_CODE, "message": message}
    return McpInvokeResult(
        is_error=True,
        text=json.dumps(payload, separators=(",", ":")),
        code=VALIDATION_ERROR_CODE,
        structured=payload,
    )


def _schema_validation_error(error: Exception) -> McpInvokeResult:
    if isinstance(error, ValidationError):
        details = error.errors(include_url=False, include_input=False)
        if len(details) == 1 and details[0]["type"] == SAFE_VALIDATION_ERROR_TYPE:
            return _validation_error(details[0]["msg"])
    return _validation_error()


def _safe_failure(code: str, message: str, hint: str | None = None) -> McpInvokeResult:
    payload = {"code": code, "message": message}
    legacy_code = _LEGACY_CODE_ALIASES.get(code)
    if legacy_code is not None:
        payload["legacy_code"] = legacy_code
    if hint is not None:
        payload["hint"] = hint
    return McpInvokeResult(
        is_error=True,
        text=json.dumps(payload, separators=(",", ":")),
        code=code,
        structured=payload,
    )


def _approval_required() -> McpInvokeResult:
    return _safe_failure(APPROVAL_REQUIRED_CODE, "Human approval is required for this tool")


def _approval_declined() -> McpInvokeResult:
    return _safe_failure(APPROVAL_DECLINED_CODE, "The tool call was not approved")


def _generic_error() -> McpInvokeResult:
    payload = {"code": GENERIC_ERROR_CODE, "message": "Tool invocation failed"}
    return McpInvokeResult(
        is_error=True,
        text=json.dumps(payload, separators=(",", ":")),
        code=GENERIC_ERROR_CODE,
        structured=payload,
    )


def _schema_for_tool(tool: Tool) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None:
        input_schema: Mapping[str, Any] = {"type": "object", "properties": {}}
    else:
        input_schema = args_schema.model_json_schema()
    output_schema = getattr(tool, "output_schema", None)
    if output_schema is None:
        return input_schema, None
    return input_schema, output_schema.model_json_schema()


@dataclass(slots=True)
class McpToolContribution:
    """A contributeable MCP tool — either eager or lazy."""

    tool_id: str
    pack_id: str | None
    factory: ToolFactory
    _cached: Tool | None = None

    def get(self) -> Tool:
        if self._cached is None:
            self._cached = self.factory()
        return self._cached


class McpToolRegistry:
    """Authorize and invoke MCP tools without a check-then-get gap."""

    def __init__(
        self,
        *,
        contributions: Sequence[McpToolContribution],
        enabled_packs: Sequence[str],
        approval_policy: ToolApprovalPolicy | None = None,
    ) -> None:
        by_id: dict[str, McpToolContribution] = {}
        id_by_name: dict[str, str] = {}
        tool_pack: dict[str, str | None] = {}
        for item in contributions:
            if item.tool_id in by_id:
                raise ValueError(f"duplicate MCP tool id: {item.tool_id}")
            name = mcp_tool_name(item.tool_id)
            if name in id_by_name:
                raise ValueError(f"duplicate MCP tool name: {name}")
            by_id[item.tool_id] = item
            id_by_name[name] = item.tool_id
            tool_pack[item.tool_id] = item.pack_id
        self._by_id = by_id
        self._id_by_name = id_by_name
        self._policy = McpAccessPolicy(
            enabled_packs=frozenset(enabled_packs),
            tool_pack=tool_pack,
        )
        self._approval_policy = approval_policy or ToolApprovalPolicy()

    def list_effective(self, caller: McpCallerContext) -> tuple[McpToolDescriptor, ...]:
        """Return descriptors for tools effective for *caller*."""
        descriptors: list[McpToolDescriptor] = []
        for tool_id in self._policy.effective_ids(caller):
            tool = self._by_id[tool_id].get()
            input_schema, output_schema = _schema_for_tool(tool)
            descriptors.append(
                McpToolDescriptor(
                    name=mcp_tool_name(tool_id),
                    description=tool.description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                )
            )
        return tuple(descriptors)

    def _failure_hint(
        self, caller: McpCallerContext, tool: Tool, code: str
    ) -> str | None:
        hints = getattr(tool, "failure_hints", None) or {}
        hinted = hints.get(code)
        if hinted is None:
            return None
        required_tool_id, hint = hinted
        if required_tool_id not in self._by_id:
            return None
        if not self._policy.is_effective(caller, required_tool_id):
            return None
        return hint

    def invoke_authorized(
        self,
        caller: McpCallerContext,
        tool_id: str,
        arguments: Mapping[str, object] | None,
        approve: McpApprovalGate | None = None,
    ) -> McpInvokeResult:
        """Atomically authorize, validate, approve, and invoke *tool_id*.

        *tool_id* may be the dotted registry id or its advertised MCP name.
        Tools the approval policy lists run only after *approve* returns True;
        a missing or failing gate fails closed (ADR 0010).
        """
        tool_id = self._id_by_name.get(tool_id, tool_id)
        if not self._policy.is_effective(caller, tool_id):
            return _tool_unavailable()
        contribution = self._by_id[tool_id]
        try:
            tool = contribution.get()
        except Exception:
            logger.exception("mcp_tool_factory_failed tool=%s", tool_id)
            return _generic_error()
        args = dict(arguments or {})
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None:
            try:
                args_schema.model_validate(args)
            except Exception as error:
                return _schema_validation_error(error)
        if self._approval_policy.requires_approval(tool_id):
            denied = self._approve(caller, tool_id, tool, args, approve)
            if denied is not None:
                return denied
        try:
            result = tool.run(args)
        except Exception as error:
            return self._failure(caller, tool_id, tool, error)
        if not isinstance(result, str):
            logger.error("mcp_tool_non_string tool=%s", tool_id)
            return _generic_error()
        structured: Mapping[str, Any] | None = None
        output_schema = getattr(tool, "output_schema", None)
        if output_schema is not None:
            try:
                parsed = json.loads(result)
                structured = output_schema.model_validate(parsed).model_dump(
                    mode="json"
                )
                result = json.dumps(structured, separators=(",", ":"))
            except Exception:
                logger.exception("mcp_tool_output_invalid tool=%s", tool_id)
                return _generic_error()
        return McpInvokeResult(is_error=False, text=result, structured=structured)

    def _approve(
        self,
        caller: McpCallerContext,
        tool_id: str,
        tool: Tool,
        args: Mapping[str, object],
        approve: McpApprovalGate | None,
    ) -> McpInvokeResult | None:
        if approve is None:
            logger.info("mcp_tool_approval tool=%s outcome=required", tool_id)
            return _approval_required()
        hints_for = getattr(tool, "approval_hints", None)
        try:
            hints = hints_for(args) if callable(hints_for) else None
        except Exception as error:
            return self._failure(caller, tool_id, tool, error)
        pending = project_pending_approval(
            approval_id=uuid.uuid4().hex,
            tool_name=tool_id,
            arguments={},
            hints=hints,
        )
        try:
            approved = approve(pending) is True
        except Exception:
            logger.info("mcp_tool_approval tool=%s outcome=gate_unavailable", tool_id)
            return _approval_required()
        logger.info(
            "mcp_tool_approval tool=%s outcome=%s",
            tool_id,
            "approved" if approved else "declined",
        )
        return None if approved else _approval_declined()

    def _failure(
        self,
        caller: McpCallerContext,
        tool_id: str,
        tool: Tool,
        error: Exception,
    ) -> McpInvokeResult:
        if isinstance(error, ToolArgumentValidationError):
            return _validation_error()
        if isinstance(error, ToolFailureError):
            if type(error) is ToolUnavailableError:
                return _tool_unavailable()
            safe = _SAFE_FAILURES.get(type(error))
            if safe is not None:
                logger.info("mcp_tool_outcome tool=%s code=%s", tool_id, safe[0])
                return _safe_failure(*safe, self._failure_hint(caller, tool, safe[0]))
            logger.info("mcp_tool_failure tool=%s", tool_id)
            return _generic_error()
        logger.exception("mcp_tool_unexpected tool=%s", tool_id, exc_info=error)
        return _generic_error()
