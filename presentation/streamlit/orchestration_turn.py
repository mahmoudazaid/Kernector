"""Orchestration-turn outcome mapping for the Streamlit presentation layer.

Owns ``OrchestrateSoftwareDeliveryRequest`` construction. Widgets and ``st``
calls stay in ``app.py``. Tool argument construction and chaining stay in
application orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass

from application.contracts import (
    OrchestrateSoftwareDeliveryRequest,
    OrchestrateSoftwareDeliveryResponse,
    SoftwareDeliveryIntent,
)
from application.errors import ApplicationValidationError
from application.orchestrate_software_delivery import OrchestrateSoftwareDelivery
from domain.errors import DomainValidationError, ProviderError, ToolFailureError

_PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the request."
_TOOL_FAILURE_MESSAGE = "A tool failed while processing your request."
_OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while processing your request."


@dataclass(frozen=True, slots=True)
class OrchestrationTurnResult:
    """UI-neutral outcome of one Software Delivery orchestration turn.

    Attributes:
        ok (bool): Whether the use case returned a response.
        message (str): User-facing error text when ``ok`` is false.
        response (OrchestrateSoftwareDeliveryResponse | None): Result when ok.
        drop_user_turn (bool): When true, presentation must drop the user turn.
    """

    ok: bool
    message: str = ""
    response: OrchestrateSoftwareDeliveryResponse | None = None
    drop_user_turn: bool = False


def _validation_message(error: BaseException) -> str:
    text = str(error).strip()
    return text or f"The request failed ({type(error).__name__})."


def run_orchestration_turn(
    orchestrator: OrchestrateSoftwareDelivery,
    *,
    query: str,
    intent: SoftwareDeliveryIntent,
    target: str,
    output_style: str = "steps",
    retrieval_limit: int | None = None,
) -> OrchestrationTurnResult:
    """Build the orchestration contract, execute, and classify the outcome.

    Args:
        orchestrator (OrchestrateSoftwareDelivery): Application use case.
        query (str): Retrieval query from the chat input.
        intent (SoftwareDeliveryIntent): Selected Software Delivery workflow.
        target (str): Assessment subject forwarded to tools.
        output_style (str): Opaque generate/export style. Defaults to ``steps``.
        retrieval_limit (int | None): Optional retrieval cap.

    Returns:
        OrchestrationTurnResult: Success with response, or classified error.
    """
    try:
        request = OrchestrateSoftwareDeliveryRequest(
            intent=intent,
            target=target,
            query=query,
            output_style=output_style,
            retrieval_limit=retrieval_limit,
        )
        response = orchestrator.execute(request)
    except ApplicationValidationError as error:
        return OrchestrationTurnResult(
            ok=False,
            message=_validation_message(error),
            drop_user_turn=True,
        )
    except ProviderError:
        return OrchestrationTurnResult(
            ok=False,
            message=_PROVIDER_FAILURE_MESSAGE,
            drop_user_turn=False,
        )
    except ToolFailureError:
        return OrchestrationTurnResult(
            ok=False,
            message=_TOOL_FAILURE_MESSAGE,
            drop_user_turn=False,
        )
    except (DomainValidationError, RuntimeError):
        return OrchestrationTurnResult(
            ok=False,
            message=_OPERATIONAL_FAILURE_MESSAGE,
            drop_user_turn=False,
        )
    return OrchestrationTurnResult(ok=True, response=response)
