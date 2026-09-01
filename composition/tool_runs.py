"""Generic tool-call envelope shared by every domain-pack surface.

Recorded at the opaque ``InvokeTool`` boundary, so nothing here interprets a
pack payload. Presentation consumes ``ToolCallView`` without knowing which
pack produced it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

OpaqueInvoke = Callable[[str, Mapping[str, object]], str]


@dataclass(frozen=True, slots=True)
class ToolCallView:
    """One tool invocation as presentation sees it.

    Attributes:
        tool_name (str): Registered tool that ran.
        ok (bool): Whether the invocation returned instead of raising.
        result (str): Opaque tool output on success, empty on failure. Never
            parsed here — that is what keeps the envelope pack-agnostic.
    """

    tool_name: str
    ok: bool
    result: str = ""


class ToolRunFailedError(RuntimeError):
    """A tool run stopped at a failing call, with the ledger up to that point.

    The message is composition-authored and fixed; tool and vendor detail stay
    on ``__cause__``. ``calls`` is carried because a failed run's most useful
    output is which tool failed, and orchestration discards its outcomes when
    it short-circuits.

    Attributes:
        calls (tuple[ToolCallView, ...]): Envelopes recorded before the raise,
            ending with the failed one.
    """

    def __init__(self, message: str, *, calls: Sequence[ToolCallView] = ()) -> None:
        super().__init__(message)
        self.calls: tuple[ToolCallView, ...] = tuple(calls)


class ToolCallRecorder:
    """Wraps an opaque invoke callable and records one envelope per call."""

    def __init__(self, invoke: OpaqueInvoke) -> None:
        self._invoke = invoke
        self._calls: list[ToolCallView] = []

    @property
    def calls(self) -> tuple[ToolCallView, ...]:
        """Envelopes for every call so far, in invocation order."""
        return tuple(self._calls)

    def __call__(self, tool_name: str, arguments: Mapping[str, object]) -> str:
        try:
            result = self._invoke(tool_name, arguments)
        except Exception:
            self._calls.append(ToolCallView(tool_name, ok=False))
            raise
        self._calls.append(ToolCallView(tool_name, ok=True, result=result))
        return result
