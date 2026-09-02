"""Ask-turn outcome mapping for the Streamlit presentation layer.

Owns AskRequest construction and the decision to drop a rejected user turn from
session state. Widgets and ``st`` calls stay in ``app.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from application.contracts import AskRequest, AskResponse, InvokeToolResponse
from application.errors import ApplicationValidationError
from composition import GroundedAsk
from domain.errors import DomainValidationError, ProviderError, ToolFailureError
from domain.models import Message

# Fixed category sentences — presentation never renders ``str(error)`` for
# provider/tool/store failures. Exception type selects the sentence; type alone
# is never treated as proof that the exception text is safe.
_PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the request."
_TOOL_FAILURE_MESSAGE = "A tool failed while processing your request."
_OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while processing your request."


@dataclass(frozen=True, slots=True)
class AskTurnResult:
    """UI-neutral outcome of one ask submission.

    Attributes:
        ok: Whether the use case returned an answer.
        message: User-facing error text when ``ok`` is false.
        response: The ask response when ``ok`` is true.
        drop_user_turn: When true, presentation must remove the user message
            already appended to session state — a rejected query must not be
            replayed as history on the next submit.
    """

    ok: bool
    message: str = ""
    response: AskResponse | None = None
    drop_user_turn: bool = False


def _validation_message(error: BaseException) -> str:
    """Validation messages are authored at the application boundary."""
    text = str(error).strip()
    return text or f"The request failed ({type(error).__name__})."


def tool_output_lines(
    tool_outputs: Sequence[InvokeToolResponse],
) -> tuple[str, ...]:
    """Name each tool that contributed, and measure what it returned.

    The payload is measured, never parsed. Interpreting it here would put pack
    knowledge into the one part of the chat surface that must stay generic —
    ``AskResponse.tool_outputs`` is opaque by contract, and structured rendering
    belongs to a pack-specific projection adapter.
    """
    return tuple(
        f"- `{output.tool_name}` — {len(output.result)} characters"
        for output in tool_outputs
    )


def run_ask_turn(
    ask: GroundedAsk,
    *,
    query: str,
    prompt_key: str | None,
    history: Sequence[Message] = (),
    settings: Mapping[str, object] | None = None,
) -> AskTurnResult:
    """Build the ask contract, execute, and classify the outcome.

    ``AskRequest`` construction lives here so blank/malformed input raises
    ``ApplicationValidationError`` inside the mapper — never in the widget
    layer after the user turn has already been appended to session state.

    ``ApplicationValidationError`` (including ``UnknownPromptError``) means the
    boundary rejected the request — the user turn must be dropped.
    Operational failures keep the turn: the text was accepted; only the call
    failed.

    Message policy by type (fixed mapping — never ``str(error)`` for
    operational types):

    * ``ApplicationValidationError`` — boundary-authored ``str(error)``;
      ``drop_user_turn=True``.
    * ``ProviderError`` (incl. rewrite failures) — fixed provider sentence.
    * ``ToolFailureError`` — fixed tool sentence.
    * ``VectorStoreError``, ``DomainValidationError``, other ``RuntimeError`` —
      fixed operational sentence.
    """
    try:
        request = AskRequest(
            prompt_key=prompt_key,
            query=query,
            history=history,
        )
        response = ask.execute(request, settings=settings)
    except ApplicationValidationError as error:
        return AskTurnResult(
            ok=False,
            message=_validation_message(error),
            drop_user_turn=True,
        )
    except ProviderError:
        return AskTurnResult(
            ok=False,
            message=_PROVIDER_FAILURE_MESSAGE,
            drop_user_turn=False,
        )
    except ToolFailureError:
        return AskTurnResult(
            ok=False,
            message=_TOOL_FAILURE_MESSAGE,
            drop_user_turn=False,
        )
    except (DomainValidationError, RuntimeError):
        return AskTurnResult(
            ok=False,
            message=_OPERATIONAL_FAILURE_MESSAGE,
            drop_user_turn=False,
        )
    return AskTurnResult(ok=True, response=response)
