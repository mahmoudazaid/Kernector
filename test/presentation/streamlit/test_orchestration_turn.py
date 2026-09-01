"""Orchestration-turn mapping: presentation must not own tool business logic."""

from pathlib import Path

from application.contracts import (
    InvokeToolResponse,
    OrchestrateSoftwareDeliveryRequest,
    OrchestrateSoftwareDeliveryResponse,
    SoftwareDeliveryIntent,
)
from application.errors import ApplicationValidationError
from domain.errors import ToolFailureError
from presentation.streamlit.orchestration_turn import run_orchestration_turn

_FIXED_TOOL_MESSAGE = "A tool failed while processing your request."


class _RaisingOrchestrator:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls: list[OrchestrateSoftwareDeliveryRequest] = []

    def execute(
        self, request: OrchestrateSoftwareDeliveryRequest
    ) -> OrchestrateSoftwareDeliveryResponse:
        self.calls.append(request)
        raise self._error


class _OkOrchestrator:
    def __init__(self) -> None:
        self.calls: list[OrchestrateSoftwareDeliveryRequest] = []

    def execute(
        self, request: OrchestrateSoftwareDeliveryRequest
    ) -> OrchestrateSoftwareDeliveryResponse:
        self.calls.append(request)
        return OrchestrateSoftwareDeliveryResponse(
            answer="Scored software-delivery risk from retrieved evidence.",
            tool_outputs=[InvokeToolResponse("software_delivery.risk_score", '{"score":40}')],
        )


def test_streamlit_app_does_not_build_orchestration_request() -> None:
    import presentation.streamlit.app as app_mod

    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    assert "OrchestrateSoftwareDeliveryRequest(" not in source
    assert "InvokeToolRequest(" not in source
    assert "packs.software_delivery" not in source


def test_successful_orchestration_returns_the_response() -> None:
    orchestrator = _OkOrchestrator()

    result = run_orchestration_turn(
        orchestrator,  # type: ignore[arg-type]
        query="MFA requirements",
        intent=SoftwareDeliveryIntent.RISK_SCORE,
        target="Assess MFA",
        output_style="steps",
    )

    assert result.ok is True
    assert result.response is not None
    assert result.response.tool_outputs[0].tool_name == "software_delivery.risk_score"
    assert orchestrator.calls[0].intent is SoftwareDeliveryIntent.RISK_SCORE
    assert orchestrator.calls[0].target == "Assess MFA"
    assert orchestrator.calls[0].query == "MFA requirements"


def test_blank_query_drops_the_user_turn() -> None:
    orchestrator = _OkOrchestrator()

    result = run_orchestration_turn(
        orchestrator,  # type: ignore[arg-type]
        query="   ",
        intent=SoftwareDeliveryIntent.RISK_SCORE,
        target="Assess MFA",
    )

    assert result.ok is False
    assert result.drop_user_turn is True
    assert "query must be non-empty" in result.message
    assert orchestrator.calls == []


def test_tool_failure_keeps_the_user_turn_with_fixed_message() -> None:
    orchestrator = _RaisingOrchestrator(
        ToolFailureError("tool dumped stack and secret-token")
    )

    result = run_orchestration_turn(
        orchestrator,  # type: ignore[arg-type]
        query="MFA requirements",
        intent=SoftwareDeliveryIntent.GENERATE_AND_EXPORT,
        target="Assess MFA",
    )

    assert result.ok is False
    assert result.drop_user_turn is False
    assert result.message == _FIXED_TOOL_MESSAGE
    assert "secret-token" not in result.message
    assert result.response is None


def test_application_validation_error_drops_the_user_turn() -> None:
    orchestrator = _RaisingOrchestrator(
        ApplicationValidationError("unknown tool_name: 'software_delivery.risk_score'")
    )

    result = run_orchestration_turn(
        orchestrator,  # type: ignore[arg-type]
        query="MFA requirements",
        intent=SoftwareDeliveryIntent.RISK_SCORE,
        target="Assess MFA",
    )

    assert result.ok is False
    assert result.drop_user_turn is True
    assert "unknown tool_name" in result.message
