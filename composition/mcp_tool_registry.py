"""Composition-owned MCP tool registry with atomic authorization."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from composition.mcp_access import McpAccessPolicy, McpCallerContext
from domain.errors import ToolArgumentValidationError, ToolFailureError
from domain.ports import Tool

logger = logging.getLogger(__name__)

TOOL_UNAVAILABLE_CODE = "tool_unavailable"
GENERIC_ERROR_CODE = "internal_error"
VALIDATION_ERROR_CODE = "validation_error"

ToolFactory = Callable[[], Tool]


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
    ) -> None:
        by_id: dict[str, McpToolContribution] = {}
        tool_pack: dict[str, str | None] = {}
        for item in contributions:
            if item.tool_id in by_id:
                raise ValueError(f"duplicate MCP tool id: {item.tool_id}")
            by_id[item.tool_id] = item
            tool_pack[item.tool_id] = item.pack_id
        self._by_id = by_id
        self._policy = McpAccessPolicy(
            enabled_packs=frozenset(enabled_packs),
            tool_pack=tool_pack,
        )

    def list_effective(self, caller: McpCallerContext) -> tuple[McpToolDescriptor, ...]:
        """Return descriptors for tools effective for *caller*."""
        descriptors: list[McpToolDescriptor] = []
        for tool_id in self._policy.effective_ids(caller):
            tool = self._by_id[tool_id].get()
            input_schema, output_schema = _schema_for_tool(tool)
            descriptors.append(
                McpToolDescriptor(
                    name=tool.name,
                    description=tool.description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                )
            )
        return tuple(descriptors)

    def invoke_authorized(
        self,
        caller: McpCallerContext,
        tool_id: str,
        arguments: Mapping[str, object] | None,
    ) -> McpInvokeResult:
        """Atomically authorize, validate, and invoke *tool_id*."""
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
            except Exception:
                return _validation_error()
        try:
            result = tool.run(args)
        except ToolArgumentValidationError:
            return _validation_error()
        except ToolFailureError:
            logger.info("mcp_tool_failure tool=%s", tool_id)
            return _generic_error()
        except Exception:
            logger.exception("mcp_tool_unexpected tool=%s", tool_id)
            return _generic_error()
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
