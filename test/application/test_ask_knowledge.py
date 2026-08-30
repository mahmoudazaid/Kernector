"""AskKnowledge grounded chat, observed through ports and public contracts."""

from collections.abc import Mapping, Sequence

import pytest

from application.ask_knowledge import AskKnowledge
from application.citations import build_citations
from application.contracts import AskRequest, RewriteRetrieveResponse
from application.grounded_rag_policy import GROUNDED_RAG_SYSTEM
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.models import AskResult, Message, PromptVariant


def _hit(
    *,
    source_id: str = "doc-1",
    content: str = "restart the worker process",
    index: int = 0,
    score: float = 0.9,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(
                SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
                title=f"title-{source_id}",
            ),
            index=index,
            content=content,
        ),
        score=score,
    )


class _FakeRewriteRetrieve:
    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = tuple(hits)
        self.requests: list[object] = []

    def execute(self, request: object) -> RewriteRetrieveResponse:
        self.requests.append(request)
        return RewriteRetrieveResponse(
            hits=self._hits,
            original_query="unused",
            rewritten_query="unused rewritten",
        )


class _RecordingChat:
    def __init__(self, answer: str = "Use the restart runbook.") -> None:
        self.answer = answer
        self.calls: list[tuple[str, Sequence[Message], Mapping[str, object]]] = []

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls.append((system, tuple(messages), dict(settings)))
        return AskResult(content=self.answer)


class _EmptyPrompts:
    def all(self) -> Mapping[str, PromptVariant]:
        return {}

    def default_key(self) -> str | None:
        return None


def test_general_ask_with_hits_returns_answer_and_citations() -> None:
    hit = _hit()
    rewrite_retrieve = _FakeRewriteRetrieve((hit,))
    chat = _RecordingChat("Use the restart runbook.")
    use_case = AskKnowledge(rewrite_retrieve, chat, _EmptyPrompts())

    response = use_case.execute(AskRequest(prompt_key=None, query="How do I restart?"))

    assert response.answer == "Use the restart runbook."
    assert response.citations == build_citations((hit,))
    assert len(chat.calls) == 1
    system, messages, _settings = chat.calls[0]
    assert system.startswith(GROUNDED_RAG_SYSTEM)
    assert "restart the worker process" in system
    assert "doc-1" in system
    assert messages[-1] == Message(role="user", content="How do I restart?")


def test_general_ask_without_evidence_states_insufficient_knowledge() -> None:
    rewrite_retrieve = _FakeRewriteRetrieve(())
    chat = _RecordingChat("should not be used")
    use_case = AskKnowledge(rewrite_retrieve, chat, _EmptyPrompts())

    response = use_case.execute(
        AskRequest(prompt_key=None, query="What is the secret formula?")
    )

    assert "insufficient" in response.answer.lower()
    assert response.citations == ()
    assert chat.calls == []


class _FixedPrompts:
    def __init__(self, *variants: PromptVariant) -> None:
        self._prompts = {variant.key: variant for variant in variants}

    def all(self) -> Mapping[str, PromptVariant]:
        return self._prompts

    def default_key(self) -> str | None:
        return next(iter(self._prompts), None)


def test_task_prompt_is_composed_with_policy_not_substituted() -> None:
    hit = _hit(content="evidence chunk")
    task = PromptVariant(
        key="role_qa",
        name="Role Q&A",
        description="Story mode",
        system="TASK PROMPT BODY: answer as a coach.",
    )
    chat = _RecordingChat("coached answer")
    use_case = AskKnowledge(_FakeRewriteRetrieve((hit,)), chat, _FixedPrompts(task))

    response = use_case.execute(
        AskRequest(prompt_key="role_qa", query="How should I prepare?")
    )

    assert response.answer == "coached answer"
    system = chat.calls[0][0]
    assert system.startswith(GROUNDED_RAG_SYSTEM)
    assert "TASK PROMPT BODY: answer as a coach." in system
    assert system.index(GROUNDED_RAG_SYSTEM) < system.index("TASK PROMPT BODY")
    assert "evidence chunk" in system


def test_unknown_prompt_key_raises_typed_error() -> None:
    from application.ask_knowledge import UnknownPromptError

    use_case = AskKnowledge(
        _FakeRewriteRetrieve((_hit(),)),
        _RecordingChat(),
        _EmptyPrompts(),
    )

    with pytest.raises(UnknownPromptError, match="Unknown prompt key"):
        use_case.execute(AskRequest(prompt_key="missing_key", query="Anything?"))
