"""Tests for generic ToolRegistry and InvokeTool."""

from collections.abc import Mapping
import logging

import pytest

from application import observability
from application.contracts import InvokeToolRequest
from application.errors import ApplicationValidationError, ConfigurationError
from application.invoke_tool import InvokeTool, ToolRegistry
from domain.errors import ToolArgumentValidationError, ToolFailureError
from test.log_record import flatten_log_record, operation_payload, operation_records

class _FakeTool:
    def __init__(self, name: str = "fake.tool", result: str = "ok") -> None:
        self._name = name
        self._result = result
        self.calls: list[Mapping[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake"

    def run(self, arguments: Mapping[str, object]) -> str:
        self.calls.append(arguments)
        return self._result


class _SpyOpaqueTool(_FakeTool):
    """Fails if the use case inspects risk/source payload fields."""

    def run(self, arguments: Mapping[str, object]) -> str:
        # Detect application-layer parsing by requiring opaque round-trip only.
        assert "source_type" not in arguments
        assert "factors" not in arguments
        return super().run(arguments)


def test_invoke_registered_tool_returns_opaque_result() -> None:
    tool = _FakeTool(result="opaque-json")
    use_case = InvokeTool(ToolRegistry([tool]))
    response = use_case.execute(InvokeToolRequest("fake.tool", {"q": 1}))
    assert response.tool_name == "fake.tool"
    assert response.result == "opaque-json"
    assert tool.calls == [{"q": 1}]


def test_unknown_tool_name_raises_before_any_call() -> None:
    tool = _FakeTool()
    use_case = InvokeTool(ToolRegistry([tool]))
    with pytest.raises(ApplicationValidationError, match="unknown tool_name"):
        use_case.execute(InvokeToolRequest("missing.tool", {}))
    assert tool.calls == []


def test_duplicate_tool_names_fail_at_construction() -> None:
    with pytest.raises(ConfigurationError, match="duplicate"):
        ToolRegistry([_FakeTool("same"), _FakeTool("same")])


def test_blank_tool_name_fails_at_construction() -> None:
    with pytest.raises(ConfigurationError, match="non-blank"):
        ToolRegistry([_FakeTool("  ")])


def test_argument_validation_error_propagates_unchanged() -> None:
    class _Rejecting(_FakeTool):
        def run(self, arguments: Mapping[str, object]) -> str:
            raise ToolArgumentValidationError("bad args")

    use_case = InvokeTool(ToolRegistry([_Rejecting()]))
    with pytest.raises(ToolArgumentValidationError, match="bad args"):
        use_case.execute(InvokeToolRequest("fake.tool", {}))


def test_tool_failure_error_propagates_unchanged() -> None:
    class _Failing(_FakeTool):
        def run(self, arguments: Mapping[str, object]) -> str:
            raise ToolFailureError("boom")

    use_case = InvokeTool(ToolRegistry([_Failing()]))
    with pytest.raises(ToolFailureError, match="boom"):
        use_case.execute(InvokeToolRequest("fake.tool", {}))


def test_invoke_tool_never_reads_source_or_risk_fields() -> None:
    tool = _SpyOpaqueTool()
    use_case = InvokeTool(ToolRegistry([tool]))
    # Nested opaque payload must be passed through untouched.
    args = {"target": "x", "evidence": [{"source_id": "1", "source_type": "srs"}]}
    response = use_case.execute(InvokeToolRequest("fake.tool", args))
    assert response.result == "ok"
    assert tool.calls[0] is not None
    assert tool.calls[0]["evidence"][0]["source_type"] == "srs"  # type: ignore[index]


def test_invoke_tool_passes_generate_test_cases_shaped_payload_untouched() -> None:
    tool = _FakeTool(result='{"output_style":"steps","test_cases":[]}')
    use_case = InvokeTool(ToolRegistry([tool]))
    args = {
        "target": "Assess MFA",
        "output_style": "gherkin",
        "evidence": [
            {
                "source_id": "US-1",
                "source_type": "user_story",
                "text": "Need MFA",
            }
        ],
    }
    response = use_case.execute(InvokeToolRequest("fake.tool", args))
    assert response.result.startswith("{")
    assert tool.calls[0] == args


def test_invoke_success_logs_tool_and_latency_without_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_args = {"api_key": "sk-live-secret", "evidence": "CONFIDENTIAL_EVIDENCE"}
    tool = _FakeTool(result="CONFIDENTIAL_TOOL_RESULT")
    use_case = InvokeTool(ToolRegistry([tool]))
    _bound, token = observability.bind_request_id("req-tool-1")
    try:
        with caplog.at_level(logging.INFO, logger="application.invoke_tool"):
            use_case.execute(InvokeToolRequest("fake.tool", secret_args))
    finally:
        observability.reset_request_id(token)

    records = operation_records(caplog.records, operation="invoke_tool")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "success"
    assert payload["request_id"] == "req-tool-1"
    assert payload["tool"] == "fake.tool"
    assert isinstance(payload["latency_ms"], int)
    flat = flatten_log_record(records[0])
    assert "sk-live-secret" not in flat
    assert "CONFIDENTIAL_EVIDENCE" not in flat
    assert "CONFIDENTIAL_TOOL_RESULT" not in flat


def test_invoke_failure_logs_error_type_without_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    leak = "tool boom with sk-live-secret"

    class _Failing(_FakeTool):
        def run(self, arguments: Mapping[str, object]) -> str:
            raise ToolFailureError(leak)

    use_case = InvokeTool(ToolRegistry([_Failing()]))
    with caplog.at_level(logging.ERROR, logger="application.invoke_tool"):
        with pytest.raises(ToolFailureError, match="sk-live-secret"):
            use_case.execute(InvokeToolRequest("fake.tool", {"q": 1}))

    records = operation_records(caplog.records, operation="invoke_tool")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "error"
    assert payload["tool"] == "fake.tool"
    assert payload["error_type"] == "ToolFailureError"
    assert records[0].exc_info is None
    flat = flatten_log_record(records[0])
    assert leak not in flat
    assert "sk-live-secret" not in flat
