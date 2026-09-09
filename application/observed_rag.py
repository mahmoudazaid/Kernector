"""Same-run observation of a grounded ask: answer, citations, generation hits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from application.contracts import AskRequest, AskResponse, Citation, RunMeta
from application.errors import ApplicationValidationError
from application.evaluation_contracts import EvalCase
from domain.knowledge import ScoredChunk


@dataclass(frozen=True, slots=True)
class AnswerModelMetadata:
    """Effective answer-model identity with no secrets.

    Args:
        provider (str): Chat provider id used to generate the answer.
        model (str): Model id used to generate the answer.
    """

    provider: str
    model: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ApplicationValidationError("provider must be a non-empty string")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ApplicationValidationError("model must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RagObservation:
    """One ask case's visible answer plus the hits that entered generation.

    Args:
        case_id (str): Eval case identifier.
        query (str): Case query.
        answer (str): Visible answer text.
        citations (Sequence[Citation]): Product citations from that turn.
        retrieved_contexts (Sequence[ScoredChunk]): Hits that entered generation.
        run (RunMeta | None): Safe run metadata.
        answer_model (AnswerModelMetadata): Answer-model identity.
    """

    case_id: str
    query: str
    answer: str
    citations: Sequence[Citation]
    retrieved_contexts: Sequence[ScoredChunk]
    run: RunMeta | None
    answer_model: AnswerModelMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ApplicationValidationError("case_id must be a non-empty string")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ApplicationValidationError("query must be a non-empty string")
        if not isinstance(self.answer, str) or not self.answer.strip():
            raise ApplicationValidationError("answer must be a non-empty string")
        if not isinstance(self.answer_model, AnswerModelMetadata):
            raise ApplicationValidationError(
                "answer_model must be an AnswerModelMetadata, "
                f"got {type(self.answer_model).__name__}"
            )
        if self.run is not None and not isinstance(self.run, RunMeta):
            raise ApplicationValidationError(
                f"run must be a RunMeta, got {type(self.run).__name__}"
            )
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(self, "retrieved_contexts", tuple(self.retrieved_contexts))


class RetrievalRecorder:
    """Instance-scoped retrieve log for one ObservedRagRunner."""

    def __init__(self) -> None:
        self._calls: list[tuple[ScoredChunk, ...]] = []

    def clear(self) -> None:
        """Drop recorded retrieve calls."""
        self._calls.clear()

    def record(self, hits: Sequence[ScoredChunk]) -> None:
        """Append one retrieve's hits."""
        self._calls.append(tuple(hits))

    @property
    def calls(self) -> tuple[tuple[ScoredChunk, ...], ...]:
        """Recorded retrieve hit tuples, oldest first."""
        return tuple(self._calls)


class RecordingRewriteAndRetrieve:
    """Forwards rewrite-and-retrieve and records the hits from each call.

    Args:
        inner: Rewrite-and-retrieve collaborator with ``execute``.
        recorder (RetrievalRecorder): Destination for recorded hits.
    """

    def __init__(self, inner: object, recorder: RetrievalRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def execute(self, request: object) -> object:
        """Run ``inner.execute`` and record ``response.hits``."""
        response = self._inner.execute(request)  # type: ignore[attr-defined]
        self._recorder.record(response.hits)
        return response


class ObservedRagRunner:
    """Run one ask case and capture the exact hits used for generation.

    Wraps the rewrite-and-retrieve seam already injected into ask. Does not
    retrieve a second time.

    Args:
        ask: Ask collaborator (``execute(AskRequest) -> AskResponse``).
        recorder (RetrievalRecorder): Recorder wrapping that ask's retrieve.
        answer_model (AnswerModelMetadata): Effective answer-model metadata.
        relevance_threshold (float): Cosine floor when ``keep_retrieved_hits``
            is false. Defaults to ``0.0``.
        keep_retrieved_hits (bool): When true, all recorded hits entered
            generation (hybrid fused scores). Defaults to ``True``.
    """

    def __init__(
        self,
        ask: object,
        recorder: RetrievalRecorder,
        answer_model: AnswerModelMetadata,
        *,
        relevance_threshold: float = 0.0,
        keep_retrieved_hits: bool = True,
    ) -> None:
        self._ask = ask
        self._recorder = recorder
        self._answer_model = answer_model
        self._relevance_threshold = relevance_threshold
        self._keep_retrieved_hits = keep_retrieved_hits

    def execute(self, case: EvalCase) -> RagObservation:
        """Ask once, require exactly one retrieve, and return the observation.

        Args:
            case (EvalCase): Ask case with ``query`` and ``k``.

        Returns:
            RagObservation: Answer, citations, and generation-time hits.

        Raises:
            ApplicationValidationError: Retrieve ran zero or multiple times.
        """
        self._recorder.clear()
        response: AskResponse = self._ask.execute(
            AskRequest(query=case.query, retrieval_limit=case.k)
        )
        if len(self._recorder.calls) != 1:
            raise ApplicationValidationError(
                f"expected exactly one retrieve for case {case.id}, "
                f"got {len(self._recorder.calls)}"
            )
        contexts = _generation_contexts(
            self._recorder.calls[0],
            response,
            keep_retrieved_hits=self._keep_retrieved_hits,
            relevance_threshold=self._relevance_threshold,
        )
        return RagObservation(
            case_id=case.id,
            query=case.query or "",
            answer=response.answer,
            citations=response.citations,
            retrieved_contexts=contexts,
            run=response.run,
            answer_model=self._answer_model,
        )


def _generation_contexts(
    recorded: Sequence[ScoredChunk],
    response: AskResponse,
    *,
    keep_retrieved_hits: bool,
    relevance_threshold: float,
) -> tuple[ScoredChunk, ...]:
    if response.run is not None and response.run.outcome == "insufficient":
        return ()
    if keep_retrieved_hits:
        return tuple(recorded)
    return tuple(hit for hit in recorded if hit.score >= relevance_threshold)


def observation_from_ask_response(
    case: EvalCase,
    response: AskResponse,
    hits: Sequence[ScoredChunk],
    answer_model: AnswerModelMetadata,
) -> RagObservation:
    """Build an observation for tests that already hold ask output and hits.

    Args:
        case (EvalCase): Ask case.
        response (AskResponse): Ask output.
        hits (Sequence[ScoredChunk]): Generation-time hits.
        answer_model (AnswerModelMetadata): Answer-model identity.

    Returns:
        RagObservation: Frozen observation.
    """
    return RagObservation(
        case_id=case.id,
        query=case.query or "",
        answer=response.answer,
        citations=response.citations,
        retrieved_contexts=tuple(hits),
        run=response.run,
        answer_model=answer_model,
    )
