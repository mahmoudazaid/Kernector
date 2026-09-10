"""Same-run observation of a grounded ask: answer, citations, generation hits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from application.contracts import AskRequest, AskResponse, Citation, RunMeta
from application.errors import ApplicationValidationError, ObservationIntegrityError
from application.evaluation_contracts import EvalCase
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
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
        shared_retrieve_hits (bool): True unless a populated ``hit_count``
            disagreed with generation hits. Missing ``hit_count`` is treated as
            unknown and does not fail this check.
    """

    case_id: str
    query: str
    answer: str
    citations: Sequence[Citation]
    retrieved_contexts: Sequence[ScoredChunk]
    run: RunMeta | None
    answer_model: AnswerModelMetadata
    shared_retrieve_hits: bool = True

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
    retrieve a second time. Generation hits come from ``AskResponse``, not a
    reconstructed filter.

    Args:
        ask: Ask collaborator (``execute(AskRequest) -> AskResponse``).
        recorder (RetrievalRecorder): Recorder wrapping that ask's retrieve.
        answer_model (AnswerModelMetadata): Effective answer-model metadata.
    """

    def __init__(
        self,
        ask: object,
        recorder: RetrievalRecorder,
        answer_model: AnswerModelMetadata,
    ) -> None:
        self._ask = ask
        self._recorder = recorder
        self._answer_model = answer_model

    def execute(self, case: EvalCase) -> RagObservation:
        """Ask once, require exactly one retrieve, and return the observation.

        Args:
            case (EvalCase): Ask case with ``query`` and ``k``.

        Returns:
            RagObservation: Answer, citations, and generation-time hits.

        Raises:
            ObservationIntegrityError: Retrieve count or hit-sharing failed.
        """
        self._recorder.clear()
        response: AskResponse = self._ask.execute(
            AskRequest(query=case.query, retrieval_limit=case.k)
        )
        if len(self._recorder.calls) != 1:
            raise ObservationIntegrityError(
                f"expected exactly one retrieve for case {case.id}, "
                f"got {len(self._recorder.calls)}"
            )
        recorded = self._recorder.calls[0]
        insufficient = (
            response.run is not None and response.run.outcome == "insufficient"
        )
        generation = tuple(response.generation_hits)
        if insufficient:
            if response.answer != INSUFFICIENT_KNOWLEDGE_ANSWER:
                raise ObservationIntegrityError(
                    f"insufficient outcome requires the insufficient answer "
                    f"for case {case.id}"
                )
            if generation:
                raise ObservationIntegrityError(
                    f"insufficient outcome must not carry generation_hits "
                    f"for case {case.id}"
                )
            contexts: tuple[ScoredChunk, ...] = ()
            reported = response.run.hit_count
            if reported is not None and reported != 0:
                raise ObservationIntegrityError(
                    f"insufficient outcome hit_count must be 0 for case {case.id}"
                )
            # hit_count already validated above; mismatch cannot reach here.
            shared = True
        else:
            if not generation and recorded:
                raise ObservationIntegrityError(
                    f"generation_hits missing for case {case.id}"
                )
            recorded_keys = {_hit_key(hit) for hit in recorded}
            if any(_hit_key(hit) not in recorded_keys for hit in generation):
                raise ObservationIntegrityError(
                    f"generation_hits do not match retrieve for case {case.id}"
                )
            contexts = generation
            reported = None if response.run is None else response.run.hit_count
            shared = reported is None or reported == len(contexts)
        return RagObservation(
            case_id=case.id,
            query=case.query or "",
            answer=response.answer,
            citations=response.citations,
            retrieved_contexts=contexts,
            run=response.run,
            answer_model=self._answer_model,
            shared_retrieve_hits=shared,
        )


def _hit_key(hit: ScoredChunk) -> tuple[object, ...]:
    reference = hit.chunk.reference
    return (reference.source_id, reference.source_type, hit.chunk.index)
