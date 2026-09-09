"""ObservedRagRunner records exactly one retrieve and returns generation hits."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from application.contracts import (
    AskRequest,
    AskResponse,
    RetrieveRequest,
    RewriteRetrieveResponse,
    RunMeta,
)
from application.errors import ObservationIntegrityError
from application.evaluation_contracts import EvalCase, EvalCitationLabel
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from application.observed_rag import (
    AnswerModelMetadata,
    ObservedRagRunner,
    RecordingRewriteAndRetrieve,
    RetrievalRecorder,
)
from domain.knowledge import DocumentChunk, ScoredChunk, SourceMetadata, SourceReference


def _hit(source_id: str, *, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, "knowledge_document")),
            index=0,
            content="chunk",
        ),
        score=score,
    )


def _ask_case() -> EvalCase:
    return EvalCase(
        id="cite-1",
        case_class="citation_provenance",
        kind="ask",
        query="checkout retry",
        k=5,
        expected_answer_mode="grounded",
        expected_source_ids=("doc-a",),
        expected_citations=(EvalCitationLabel("doc-a", "knowledge_document", 0),),
    )


class _FakeRewrite:
    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self.hits = tuple(hits)
        self.calls = 0

    def execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse:
        self.calls += 1
        return RewriteRetrieveResponse(
            original_query=request.query,
            rewritten_query=request.query,
            hits=self.hits,
        )


class _AskThatRetrieves:
    def __init__(self, rewrite: object, response: AskResponse, times: int = 1) -> None:
        self._rewrite = rewrite
        self._response = response
        self._times = times

    def execute(
        self,
        request: AskRequest,
        settings: object = None,
    ) -> AskResponse:
        del settings
        for _ in range(self._times):
            self._rewrite.execute(
                RetrieveRequest(query=request.query, retrieval_limit=request.retrieval_limit or 5)
            )
        return self._response


def test_observed_runner_returns_same_run_hits_after_one_retrieve() -> None:
    hits = (_hit("doc-a"), _hit("doc-b"))
    rewrite = _FakeRewrite(hits)
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer="Use backoff.",
        run=RunMeta(outcome="success", hit_count=2),
        generation_hits=hits,
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    observation = runner.execute(_ask_case())

    assert rewrite.calls == 1
    assert observation.retrieved_contexts == hits
    assert observation.answer == "Use backoff."
    assert observation.answer_model.model == "eval-offline"


def test_observed_runner_rejects_zero_retrieves() -> None:
    recorder = RetrievalRecorder()
    response = AskResponse(
        answer="Use backoff.",
        run=RunMeta(outcome="success", hit_count=1),
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(_FakeRewrite((_hit("doc-a"),)), response, times=0),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    with pytest.raises(ObservationIntegrityError, match="exactly one retrieve"):
        runner.execute(_ask_case())


def test_observed_runner_rejects_two_retrieves() -> None:
    rewrite = _FakeRewrite((_hit("doc-a"),))
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer="Use backoff.",
        run=RunMeta(outcome="success", hit_count=1),
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response, times=2),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    with pytest.raises(ObservationIntegrityError, match="exactly one retrieve"):
        runner.execute(_ask_case())


def test_insufficient_outcome_has_empty_generation_contexts() -> None:
    rewrite = _FakeRewrite((_hit("noise", score=0.1),))
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
        run=RunMeta(outcome="insufficient", hit_count=0),
        generation_hits=(),
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    observation = runner.execute(_ask_case())

    assert observation.retrieved_contexts == ()
    assert observation.shared_retrieve_hits is True
    assert rewrite.calls == 1


def test_insufficient_with_generation_hits_raises() -> None:
    rewrite = _FakeRewrite((_hit("noise", score=0.1),))
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
        run=RunMeta(outcome="insufficient", hit_count=0),
        generation_hits=(_hit("noise", score=0.1),),
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    with pytest.raises(ObservationIntegrityError, match="generation_hits"):
        runner.execute(_ask_case())


def test_hit_count_mismatch_raises_observation_integrity() -> None:
    hits = (_hit("doc-a"),)
    rewrite = _FakeRewrite(hits)
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer="Use backoff.",
        run=RunMeta(outcome="success", hit_count=5),
        generation_hits=hits,
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    with pytest.raises(ObservationIntegrityError, match="hit_count"):
        runner.execute(_ask_case())


def test_missing_hit_count_still_shares_when_generation_matches() -> None:
    hits = (_hit("doc-a"),)
    rewrite = _FakeRewrite(hits)
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer="Use backoff.",
        run=RunMeta(outcome="success"),
        generation_hits=hits,
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    observation = runner.execute(_ask_case())

    assert observation.retrieved_contexts == hits
    assert observation.shared_retrieve_hits is True


def test_dropped_generation_hits_raise() -> None:
    hits = (_hit("doc-a"),)
    rewrite = _FakeRewrite(hits)
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite, recorder)
    response = AskResponse(
        answer="Use backoff.",
        run=RunMeta(outcome="success", hit_count=1),
    )
    runner = ObservedRagRunner(
        _AskThatRetrieves(recording, response),
        recorder,
        AnswerModelMetadata(provider="eval-offline", model="eval-offline"),
    )

    with pytest.raises(ObservationIntegrityError, match="generation_hits missing"):
        runner.execute(_ask_case())
