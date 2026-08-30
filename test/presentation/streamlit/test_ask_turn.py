"""Ask-turn mapping: validation errors must not leave a rejected turn behind."""

from collections.abc import Mapping
from pathlib import Path

from application.contracts import AskRequest, AskResponse
from application.errors import ApplicationValidationError
from presentation.streamlit.ask_turn import run_ask_turn


class _RaisingAsk:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls: list[AskRequest] = []

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        self.calls.append(request)
        raise self._error


class _OkAsk:
    def __init__(self) -> None:
        self.calls: list[AskRequest] = []

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        self.calls.append(request)
        return AskResponse(answer="ok")


def test_streamlit_app_does_not_duplicate_input_validation() -> None:
    """Length and blank checks live at the application boundary, not in the UI."""
    import presentation.streamlit.app as app_mod

    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    assert "validate_input" not in source


def test_application_validation_error_drops_the_user_turn() -> None:
    ask = _RaisingAsk(ApplicationValidationError("query must be at most 10 characters, got 11"))

    result = run_ask_turn(
        ask,  # type: ignore[arg-type]
        AskRequest(query="x" * 11),
    )

    assert result.ok is False
    assert result.drop_user_turn is True
    assert "at most 10" in result.message
    assert result.response is None
    assert len(ask.calls) == 1


def test_operational_failure_keeps_the_user_turn() -> None:
    ask = _RaisingAsk(RuntimeError("vector store unavailable"))

    result = run_ask_turn(
        ask,  # type: ignore[arg-type]
        AskRequest(query="How do I restart?"),
    )

    assert result.ok is False
    assert result.drop_user_turn is False
    assert "vector store unavailable" in result.message


def test_successful_ask_returns_the_response() -> None:
    ask = _OkAsk()

    result = run_ask_turn(
        ask,  # type: ignore[arg-type]
        AskRequest(query="How do I restart?"),
    )

    assert result.ok is True
    assert result.drop_user_turn is False
    assert result.response is not None
    assert result.response.answer == "ok"
