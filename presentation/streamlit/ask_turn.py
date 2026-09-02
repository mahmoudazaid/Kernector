"""Ask-turn outcome mapping for the Streamlit presentation layer.

Owns AskRequest construction and the decision to drop a rejected user turn from
session state. Widgets and ``st`` calls stay in ``app.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableSequence, Sequence
from dataclasses import dataclass
from typing import Any

from application.contracts import AskRequest, AskResponse, InvokeToolResponse, RunMeta
from application.errors import ApplicationValidationError
from application.observability import bind_request_id, reset_request_id
from composition import GroundedAsk
from domain.errors import DomainValidationError, ProviderError, ToolFailureError
from domain.models import Message

# Fixed category sentences — presentation never renders ``str(error)`` for
# provider/tool/store failures. Exception type selects the sentence; type alone
# is never treated as proof that the exception text is safe.
_PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the request."
_TOOL_FAILURE_MESSAGE = "A tool failed while processing your request."
_OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while processing your request."

_DISPLAY_ONLY_KEY = "display_only"


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
        run: Safe execution metadata when execution started; ``None`` when the
            request never reached ``execute`` (e.g. blank query construction).
    """

    ok: bool
    message: str = ""
    response: AskResponse | None = None
    drop_user_turn: bool = False
    run: RunMeta | None = None


def _validation_message(error: BaseException) -> str:
    """Validation messages are authored at the application boundary."""
    text = str(error).strip()
    return text or f"The request failed ({type(error).__name__})."


def _error_run(request_id: str | None, error: BaseException) -> RunMeta | None:
    """Build sanitized failure metadata; omit when execution never started."""
    if request_id is None:
        return None
    return RunMeta(
        request_id=request_id,
        outcome="error",
        error_type=type(error).__name__,
    )


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


def messages_for_model_history(
    session_messages: Sequence[Mapping[str, Any]],
) -> tuple[Message, ...]:
    """Project session messages into model history, skipping display-only entries.

    Display-only assistant rows (sanitized provider/operational errors) stay
    visible in the UI after Streamlit reruns but must not be replayed to the
    model on the next turn.
    """
    history: list[Message] = []
    for message in session_messages:
        if message.get(_DISPLAY_ONLY_KEY):
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        if not content.strip():
            continue
        history.append(Message(role=role, content=content))
    return tuple(history)


def display_only_error_entry(
    message: str,
    *,
    run: RunMeta | None = None,
) -> dict[str, object]:
    """Build a conversation row that renders after reruns but is not model history."""
    entry: dict[str, object] = {
        "role": "assistant",
        "content": message,
        _DISPLAY_ONLY_KEY: True,
    }
    if run is not None:
        entry["run"] = run
    return entry


def apply_ask_turn_to_session_messages(
    messages: MutableSequence[dict[str, Any]],
    result: AskTurnResult,
) -> None:
    """Mutate session messages after one ask turn.

    Successful answers append a normal assistant row. Operational failures keep
    the user turn and append a display-only sanitized error. Validation
    rejections drop the just-appended user turn and add nothing — the refused
    text must not survive into the next submit.
    """
    if result.ok:
        response = result.response
        if response is None:
            return
        messages.append(
            {
                "role": "assistant",
                "content": response.answer,
                "citations": response.citations,
                "tool_outputs": response.tool_outputs,
                "run": response.run,
            }
        )
        return
    if result.drop_user_turn:
        if messages and messages[-1].get("role") == "user":
            messages.pop()
        return
    messages.append(display_only_error_entry(result.message, run=result.run))


def run_ask_turn(
    ask: GroundedAsk,
    *,
    query: str,
    prompt_key: str | None = None,
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

    Binds a ``request_id`` before ``execute`` so ``CorrelatedAsk`` reuses it and
    failures can still expose sanitized ``AskTurnResult.run``.

    Message policy by type (fixed mapping — never ``str(error)`` for
    operational types):

    * ``ApplicationValidationError`` — boundary-authored ``str(error)``;
      ``drop_user_turn=True``.
    * ``ProviderError`` (incl. rewrite failures) — fixed provider sentence.
    * ``ToolFailureError`` — fixed tool sentence.
    * ``VectorStoreError``, ``DomainValidationError``, other ``RuntimeError`` —
      fixed operational sentence.
    """
    request_id: str | None = None
    token = None
    try:
        request = AskRequest(
            prompt_key=prompt_key,
            query=query,
            history=history,
        )
        request_id, token = bind_request_id()
        response = ask.execute(request, settings=settings)
    except ApplicationValidationError as error:
        return AskTurnResult(
            ok=False,
            message=_validation_message(error),
            drop_user_turn=True,
            run=_error_run(request_id, error),
        )
    except ProviderError as error:
        return AskTurnResult(
            ok=False,
            message=_PROVIDER_FAILURE_MESSAGE,
            drop_user_turn=False,
            run=_error_run(request_id, error),
        )
    except ToolFailureError as error:
        return AskTurnResult(
            ok=False,
            message=_TOOL_FAILURE_MESSAGE,
            drop_user_turn=False,
            run=_error_run(request_id, error),
        )
    except (DomainValidationError, RuntimeError) as error:
        return AskTurnResult(
            ok=False,
            message=_OPERATIONAL_FAILURE_MESSAGE,
            drop_user_turn=False,
            run=_error_run(request_id, error),
        )
    finally:
        reset_request_id(token)
    return AskTurnResult(ok=True, response=response, run=response.run)
