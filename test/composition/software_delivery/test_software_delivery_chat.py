"""Chat-time Software Delivery tool runs: recorder, retrieval guard, projection.

Doubles are duck-typed on the pack's outcome shapes rather than imported: this
module must not load ``packs`` at import time, and neither must its tests, so
that ``import composition`` stays pack-free in a fresh interpreter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from types import SimpleNamespace

import pytest

from application.contracts import InvokeToolResponse
from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition.software_delivery.chat import (
    SOFTWARE_DELIVERY_TEST_STYLES,
    PackSoftwareDeliveryChat,
    ToolCallRecorder,
    ToolRunFailedError,
    project_software_delivery_run_view,
    tool_run_answer,
)
from composition.software_delivery.tools import SoftwareDeliveryRunView
from composition.tools.runs import ToolCallView
from domain.errors import ToolFailureError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)

_TOOL = "pack.example_tool"
_SECOND_TOOL = "pack.second_tool"
_DRIVE_TOOL = "software_delivery.export_test_cases_google_drive"
_SUMMARY = "Export finished."


@dataclass(frozen=True)
class _DriveOutcome:
    file_id: str
    file_name: str
    destination_label: str


@dataclass(frozen=True)
class _Response:
    summary: str
    outcomes: tuple[object, ...]


def _drive() -> _DriveOutcome:
    return _DriveOutcome(
        file_id="file-1",
        file_name="test-cases.md",
        destination_label="My Drive",
    )


def _hit(
    *,
    source_id: str = "AUTH-101",
    content: str = "MFA is required.",
    index: int = 0,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, "user_story"), extra={}),
            index=index,
            content=content,
        ),
        score=0.9,
    )


class _RecordingRetrieve:
    def __init__(self, hits: tuple[ScoredChunk, ...]) -> None:
        self._hits = hits
        self.queries: list[str] = []

    def __call__(self, target: str) -> tuple[ScoredChunk, ...]:
        self.queries.append(target)
        return self._hits


class _RecordingOrchestrate:
    """Stands in for the lazily-imported pack call the container supplies."""

    def __init__(self, response: _Response, *, tools: Sequence[str] = (_TOOL,)) -> None:
        self._response = response
        self._tools = tuple(tools)
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> _Response:
        self.calls.append(dict(kwargs))
        for tool_name in self._tools:
            kwargs["invoke"](tool_name, {})  # type: ignore[operator]
        return self._response


def _ok(tool_name: str, arguments: Mapping[str, object]) -> str:
    return '{"ok": true}'


def test_each_successful_call_is_recorded_as_an_opaque_tool_output() -> None:
    """AC4: tool_outputs is the ledger of what actually ran, in call order."""
    recorder = ToolCallRecorder(_ok)

    recorder(_TOOL, {})
    recorder(_SECOND_TOOL, {})

    assert recorder.tool_outputs == (
        InvokeToolResponse(_TOOL, '{"ok": true}'),
        InvokeToolResponse(_SECOND_TOOL, '{"ok": true}'),
    )


def test_a_failed_call_is_not_recorded_as_an_output() -> None:
    """InvokeToolResponse rejects a blank result, so a failure has no entry."""

    def invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
        if tool_name == _SECOND_TOOL:
            raise ToolFailureError("openrouter 502 for key sk-live-abc")
        return '{"ok": true}'

    recorder = ToolCallRecorder(invoke)
    recorder(_TOOL, {})

    with pytest.raises(ToolFailureError):
        recorder(_SECOND_TOOL, {})

    assert recorder.tool_outputs == (InvokeToolResponse(_TOOL, '{"ok": true}'),)


def test_a_blank_result_cannot_become_a_tool_output() -> None:
    """An empty payload carries nothing and the contract will not hold it."""
    recorder = ToolCallRecorder(lambda tool_name, arguments: "")

    assert recorder(_TOOL, {}) == ""
    assert recorder.tool_outputs == ()


def test_a_run_retrieves_orchestrates_and_reports_what_ran() -> None:
    """The whole seam, offline: nothing here touches a model or a vector store."""
    retrieve = _RecordingRetrieve((_hit(),))
    orchestrate = _RecordingOrchestrate(_Response(_SUMMARY, (_drive(),)))
    runner = PackSoftwareDeliveryChat(
        retrieve=retrieve, invoke=_ok, orchestrate=orchestrate
    )

    outcome = runner.run(
        "Export test cases for AUTH-101", generate_tests=False, output_style="steps"
    )

    assert retrieve.queries == ["Export test cases for AUTH-101"]
    assert orchestrate.calls[0]["target"] == "Export test cases for AUTH-101"
    assert orchestrate.calls[0]["hits"] == (_hit(),)
    assert orchestrate.calls[0]["generate_tests"] is False
    assert orchestrate.calls[0]["output_style"] == "steps"
    assert outcome.tool_outputs == (InvokeToolResponse(_TOOL, '{"ok": true}'),)


def test_a_drive_export_run_answers_with_the_exported_file_name() -> None:
    """AC1: the answer restates typed tool output, not improvised prose."""
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response(_SUMMARY, (_drive(),))),
    )

    outcome = runner.run("Export test cases for AUTH-101")

    assert outcome.answer == (
        "Export finished.\n\nExported **test-cases.md** to Google Drive."
    )


def test_a_run_attaches_a_run_view_with_the_drive_receipt() -> None:
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response(_SUMMARY, (_drive(),))),
    )

    outcome = runner.run("Export test cases for AUTH-101")

    assert outcome.run_view is not None
    assert outcome.run_view.drive_file_id == "file-1"
    assert outcome.run_view.drive_file_name == "test-cases.md"
    assert outcome.run_view.drive_destination_label == "My Drive"
    assert outcome.run is not None
    assert outcome.run.hit_count == 1
    assert outcome.run.citation_count == 1
    assert outcome.run.model is None
    assert outcome.run.query_rewritten is None


def test_model_call_recorder_projects_latency_onto_tool_run_outcome() -> None:
    from composition.chat.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="{}",
                model="gen-model",
                latency_ms=55,
                usage=Usage(total_tokens=12),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]

    def orchestrate(**kwargs: object) -> _Response:
        # Simulate a tool calling the shared chat model.
        recording.complete("sys", (Message(role="user", content="q"),), {})
        kwargs["invoke"](_TOOL, {})  # type: ignore[operator]
        return _Response(_SUMMARY, (_drive(),))

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=orchestrate,
        model_calls=recording,
    )

    outcome = runner.run("Export test cases for AUTH-101", generate_tests=False)

    assert outcome.run is not None
    assert outcome.run.model == "gen-model"
    assert outcome.run.latency_ms == 55
    assert outcome.run.usage == Usage(total_tokens=12)
    assert outcome.run.settings == {}
    assert outcome.run.hit_count == 1
    assert outcome.run.citation_count == 1
    assert recording.consume() is None


def test_stale_recording_before_run_is_ignored_by_model_free_run() -> None:
    from composition.chat.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="stale",
                model="stale-model",
                latency_ms=99,
                usage=Usage(total_tokens=1),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="prior"),), {})

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response(_SUMMARY, (_drive(),))),
        model_calls=recording,
    )

    outcome = runner.run("Export test cases for AUTH-101", generate_tests=False)

    assert outcome.run is not None
    assert outcome.run.model is None
    assert outcome.run.latency_ms is None
    assert outcome.run.hit_count == 1
    assert recording.consume() is None


def test_failed_run_clears_model_metadata_so_next_run_does_not_inherit_it() -> None:
    from composition.chat.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="{}",
                model="failed-run-model",
                latency_ms=44,
                usage=Usage(total_tokens=8),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]

    def failing_orchestrate(**kwargs: object) -> _Response:
        recording.complete("sys", (Message(role="user", content="q"),), {})
        raise RuntimeError("orchestrate blew up")

    failing = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=failing_orchestrate,
        model_calls=recording,
    )
    with pytest.raises(ToolRunFailedError):
        failing.run("Export test cases for AUTH-101")

    assert recording.consume() is None

    following = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response(_SUMMARY, (_drive(),))),
        model_calls=recording,
    )
    outcome = following.run("Export test cases for AUTH-101", generate_tests=False)

    assert outcome.run is not None
    assert outcome.run.model is None
    assert outcome.run.latency_ms is None
    assert outcome.run.hit_count == 1


def test_projection_failure_after_model_call_clears_recorder() -> None:
    """tool_run_answer / projection errors must not leak metadata to the next run."""
    from composition.chat.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="{}",
                model="proj-fail-model",
                latency_ms=33,
                usage=Usage(total_tokens=5),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]

    def orchestrate(**kwargs: object) -> _Response:
        recording.complete("sys", (Message(role="user", content="q"),), {})
        kwargs["invoke"](_TOOL, {})  # type: ignore[operator]
        return _Response("Ran something new.", (object(),))

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=orchestrate,
        model_calls=recording,
    )
    with pytest.raises(ToolRunFailedError):
        runner.run("Export test cases for AUTH-101")

    assert recording.consume() is None


def test_fake_recorder_protocol_works_without_inner_chat_model() -> None:
    """Orchestration depends on ModelCallRecorder, not RecordingChatModel."""
    from application.contracts import RunMeta
    from domain.models import Usage

    class _FakeRecorder:
        def __init__(self) -> None:
            self._meta: RunMeta | None = None
            self.cleared = 0

        def clear(self) -> None:
            self.cleared += 1
            self._meta = None

        def consume(self) -> RunMeta | None:
            last, self._meta = self._meta, None
            return last

        def seed(self, meta: RunMeta) -> None:
            self._meta = meta

    fake = _FakeRecorder()

    def orchestrate(**kwargs: object) -> _Response:
        fake.seed(
            RunMeta(
                model="fake-model",
                latency_ms=10,
                usage=Usage(total_tokens=2),
            )
        )
        kwargs["invoke"](_TOOL, {})  # type: ignore[operator]
        return _Response(_SUMMARY, (_drive(),))

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=orchestrate,
        model_calls=fake,
    )
    outcome = runner.run("Export test cases for AUTH-101", generate_tests=False)

    assert fake.cleared >= 2  # start + finally
    assert outcome.run is not None
    assert outcome.run.model == "fake-model"
    assert outcome.run.latency_ms == 10
    assert outcome.run.hit_count == 1


def test_every_citation_came_from_the_retrieved_evidence() -> None:
    """AC2: row-level provenance survives, because the bundle never touches it."""
    hits = (
        _hit(source_id="AUTH-101", content="MFA is required.", index=0),
        _hit(source_id="AUTH-101", content="Lock after five attempts.", index=1),
    )
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve(hits),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response(_SUMMARY, (_drive(),))),
    )

    outcome = runner.run("Export test cases for AUTH-101", generate_tests=False)

    assert {citation.quote for citation in outcome.citations} <= {
        hit.chunk.content for hit in hits
    }
    assert [citation.chunk_index for citation in outcome.citations] == [0, 1]
    assert all(
        citation.reference == SourceReference("AUTH-101", "user_story")
        for citation in outcome.citations
    )


def test_an_unrecognised_outcome_is_a_failure_not_a_silent_drop() -> None:
    """A new pack outcome must not vanish from the answer without anyone noticing."""
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response("Ran something new.", (object(),))),
    )

    with pytest.raises(ToolRunFailedError) as excinfo:
        runner.run("Export test cases for AUTH-101", generate_tests=False)

    assert str(excinfo.value) == "The tool run produced an unrecognised result."


def test_nothing_relevant_retrieved_is_an_outcome_not_a_crash() -> None:
    """An empty bundle would raise a pack validation error; say what happened."""
    orchestrate = _RecordingOrchestrate(_Response("unused", ()))
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve(()), invoke=_ok, orchestrate=orchestrate
    )

    with pytest.raises(InsufficientEvidenceError):
        runner.run("Export test cases for AUTH-101")

    assert orchestrate.calls == []


def test_an_unknown_output_style_is_rejected_before_the_pack() -> None:
    retrieve = _RecordingRetrieve((_hit(),))
    orchestrate = _RecordingOrchestrate(_Response("unused", ()))
    runner = PackSoftwareDeliveryChat(
        retrieve=retrieve, invoke=_ok, orchestrate=orchestrate
    )

    with pytest.raises(ApplicationValidationError) as excinfo:
        runner.run("Export test cases for AUTH-101", output_style="prose")

    assert str(excinfo.value) == "output_style must be one of ['gherkin', 'steps']"
    assert retrieve.queries == []
    assert orchestrate.calls == []


def test_a_tool_failure_keeps_the_outputs_that_already_landed() -> None:
    """The reader learns which tools ran, never what the provider said."""

    def orchestrate(**kwargs: object) -> _Response:
        invoke = kwargs["invoke"]
        invoke(_TOOL, {})  # type: ignore[operator]
        invoke(_SECOND_TOOL, {})  # type: ignore[operator]
        raise AssertionError("unreachable")

    def invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
        if tool_name == _SECOND_TOOL:
            raise ToolFailureError("openrouter 502 for key sk-live-abc")
        return '{"ok": true}'

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=invoke,
        orchestrate=orchestrate,
    )

    with pytest.raises(ToolRunFailedError) as excinfo:
        runner.run("Export test cases for AUTH-101")

    assert str(excinfo.value) == "A tool failed during the run."
    assert "sk-live-abc" not in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ToolFailureError)
    assert excinfo.value.tool_outputs == (InvokeToolResponse(_TOOL, '{"ok": true}'),)


def test_exported_styles_match_the_pack() -> None:
    """A composition constant that drifts from the pack would 400 at the tool."""
    from packs.software_delivery.contracts import TEST_CASE_STYLES

    assert set(SOFTWARE_DELIVERY_TEST_STYLES) == set(TEST_CASE_STYLES)


def test_project_run_view_maps_drive_receipt_to_typed_view() -> None:
    """#178: typed outcomes become SoftwareDeliveryRunView without opaque payloads."""
    view = project_software_delivery_run_view(_Response(_SUMMARY, (_drive(),)))

    assert view == SoftwareDeliveryRunView(
        summary=_SUMMARY,
        calls=(
            ToolCallView(
                _DRIVE_TOOL, ok=True, summary="Exported test cases to Google Drive"
            ),
        ),
        drive_file_id="file-1",
        drive_file_name="test-cases.md",
        drive_destination_label="My Drive",
    )


def test_project_run_view_flags_a_missing_export_destination() -> None:
    view = project_software_delivery_run_view(
        _Response(
            "Save a destination first.",
            (SimpleNamespace(outcome="export_destination_required"),),
        )
    )

    assert view.export_destination_required is True
    assert view.calls == ()


@pytest.mark.parametrize(
    "outcome",
    [
        SimpleNamespace(assessment=object()),
        SimpleNamespace(result=object()),
        SimpleNamespace(markdown="# Test Cases\n"),
    ],
    ids=["assessment", "generation", "markdown"],
)
def test_retired_tool_outcomes_are_unrecognised(outcome: object) -> None:
    response = _Response("Ran a retired tool.", (outcome,))

    with pytest.raises(ToolRunFailedError):
        project_software_delivery_run_view(response)
    with pytest.raises(ToolRunFailedError):
        tool_run_answer(response)


def test_run_view_carries_no_retired_tool_fields() -> None:
    names = {field.name for field in fields(SoftwareDeliveryRunView)}

    assert names.isdisjoint({"risk", "test_cases", "markdown"})


def test_project_run_view_rejects_unrecognised_outcome() -> None:
    with pytest.raises(ToolRunFailedError) as excinfo:
        project_software_delivery_run_view(
            _Response("Ran something new.", (object(),))
        )

    assert str(excinfo.value) == "The tool run produced an unrecognised result."
