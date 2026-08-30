"""Ask-turn outcome mapping for the Streamlit presentation layer.

Owns AskRequest construction and the decision to drop a rejected user turn from
session state. Widgets and ``st`` calls stay in ``app.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from application.ask_knowledge import AskKnowledge
from application.contracts import AskRequest, AskResponse
from application.errors import ApplicationValidationError
from domain.errors import DomainValidationError
from domain.models import Message


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


def _failure_message(error: BaseException) -> str:
    """Never hand the UI an empty string: some exceptions stringify to ``''``."""
    text = str(error).strip()
    return text or f"The request failed ({type(error).__name__})."


def run_ask_turn(
    ask: AskKnowledge,
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
            message=_failure_message(error),
            drop_user_turn=True,
        )
    except (DomainValidationError, RuntimeError) as error:
        return AskTurnResult(
            ok=False,
            message=_failure_message(error),
            drop_user_turn=False,
        )
    return AskTurnResult(ok=True, response=response)
