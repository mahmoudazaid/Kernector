"""Generic tool registry and single-tool invocation use case."""

from collections.abc import Iterable
import logging
import time

from application.contracts import InvokeToolRequest, InvokeToolResponse
from application.errors import ApplicationValidationError, ConfigurationError
from application.observability import log_operation
from domain.ports import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Opaque name → tool lookup built from an iterable of tools."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        registered: dict[str, Tool] = {}
        for tool in tools:
            name = tool.name
            if not isinstance(name, str) or not name.strip():
                raise ConfigurationError("tool name must be non-blank")
            if name in registered:
                raise ConfigurationError(f"duplicate tool name: {name!r}")
            registered[name] = tool
        self._tools = registered

    def get(self, name: str) -> Tool | None:
        """Return the registered tool for ``name``, or ``None``."""
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        """Return registered tool names in sorted order."""
        return tuple(sorted(self._tools))

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools


class InvokeTool:
    """Looks up one registered tool and invokes it without interpreting payload."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, request: InvokeToolRequest) -> InvokeToolResponse:
        """Invoke exactly one tool named by ``request.tool_name``.

        Args:
            request: Validated invoke contract.

        Returns:
            Opaque string result wrapped as ``InvokeToolResponse``.

        Raises:
            ApplicationValidationError: Unknown tool name.
            ToolArgumentValidationError: Propagated from the tool.
            ToolFailureError: Propagated from the tool.
        """
        tool = self._registry.get(request.tool_name)
        if tool is None:
            raise ApplicationValidationError(
                f"unknown tool_name: {request.tool_name!r}"
            )
        started = time.perf_counter()
        try:
            result = tool.run(request.arguments)
        except Exception as error:
            latency_ms = int((time.perf_counter() - started) * 1000)
            log_operation(
                logger,
                operation="invoke_tool",
                outcome="error",
                level=logging.ERROR,
                tool=request.tool_name,
                error_type=type(error).__name__,
                latency_ms=latency_ms,
            )
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        log_operation(
            logger,
            operation="invoke_tool",
            outcome="success",
            tool=request.tool_name,
            latency_ms=latency_ms,
        )
        return InvokeToolResponse(request.tool_name, result)
