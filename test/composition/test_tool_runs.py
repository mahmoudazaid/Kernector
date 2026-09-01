"""Behavior tests for the generic tool-call envelope.

Nothing here imports ``packs``: the envelope is recorded at the opaque invoke
boundary and must stay pack-agnostic by construction.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from composition.tool_runs import ToolCallRecorder, ToolCallView, ToolRunFailedError
from domain.errors import ToolFailureError


class _RecordingInvoke:
    def __init__(self, result: str = '{"score":42}') -> None:
        self._result = result
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def __call__(self, tool_name: str, arguments: Mapping[str, object]) -> str:
        self.calls.append((tool_name, arguments))
        return self._result


class _FailingInvoke:
    def __init__(self, error: BaseException, *, fail_on: str) -> None:
        self._error = error
        self._fail_on = fail_on
        self.calls: list[str] = []

    def __call__(self, tool_name: str, arguments: Mapping[str, object]) -> str:
        self.calls.append(tool_name)
        if tool_name == self._fail_on:
            raise self._error
        return "{}"


def test_a_successful_call_is_recorded_with_its_name_and_payload() -> None:
    """AC1: the envelope carries what ran and what it returned, uninterpreted."""
    invoke = _RecordingInvoke()
    recorder = ToolCallRecorder(invoke)

    result = recorder("software_delivery.risk_score", {"target": "Assess MFA"})

    assert result == '{"score":42}'
    assert invoke.calls == [("software_delivery.risk_score", {"target": "Assess MFA"})]
    assert recorder.calls == (
        ToolCallView("software_delivery.risk_score", ok=True, result='{"score":42}'),
    )


def test_a_failing_call_is_recorded_as_failed_and_carries_no_payload() -> None:
    """AC5: a failure names the tool without shipping whatever it produced."""
    invoke = _FailingInvoke(
        ToolFailureError("chroma said no at /srv/kernector/secret"),
        fail_on="software_delivery.generate_test_cases",
    )
    recorder = ToolCallRecorder(invoke)

    recorder("software_delivery.risk_score", {})
    with pytest.raises(ToolFailureError):
        recorder("software_delivery.generate_test_cases", {})

    assert recorder.calls == (
        ToolCallView("software_delivery.risk_score", ok=True, result="{}"),
        ToolCallView("software_delivery.generate_test_cases", ok=False, result=""),
    )


def test_tool_run_failed_error_carries_the_partial_ledger() -> None:
    """The useful part of a failed run is which tool failed."""
    calls = (ToolCallView("software_delivery.risk_score", ok=True, result="{}"),)

    error = ToolRunFailedError("A tool failed during the run.", calls=calls)

    assert error.calls == calls
    assert str(error) == "A tool failed during the run."
    assert isinstance(error, RuntimeError)
