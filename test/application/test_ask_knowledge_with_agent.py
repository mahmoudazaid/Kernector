"""Agent grounded ask: retrieve via tool, then answer; citations from side channel."""

from __future__ import annotations

from collections.abc import Sequence

from application.ask_knowledge_with_agent import AskKnowledgeWithAgent
from application.citations import build_citations
from application.contracts import AskRequest, RetrieveRequest, RewriteRetrieveResponse
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from application.retrieval_citation_channel import RetrievalCitationChannel
from application.retrieve_knowledge_tool import RetrieveKnowledgeTool
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.models import AgentTurnResult
from domain.ports import Tool


def _hit(
    *,
    content: str = "restart the worker process",
    source_id: str = "doc-1",
    index: int = 3,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(
                SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
                title="Runbook",
            ),
            index=index,
            content=content,
        ),
        score=0.95,
    )


class _StubRewriteRetrieve:
    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = hits

    def execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse:
        del request
        return RewriteRetrieveResponse(
            original_query="q",
            rewritten_query="q",
            hits=self._hits,
        )


class _RetrieveThenAnswerAgent:
    """Invokes the bound retrieve tool, then returns a final answer."""

    def __init__(self) -> None:
        self.system_prompts: list[str | None] = []

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None = None,
        system_prompt: str | None = None,
    ) -> AgentTurnResult:
        del max_steps, conversation_id
        self.system_prompts.append(system_prompt)
        tools[0].run({"query": goal})
        return AgentTurnResult(
            content="Restart the worker using the runbook steps.",
            steps=2,
        )


class _AnswerWithoutRetrieveAgent:
    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None = None,
        system_prompt: str | None = None,
    ) -> AgentTurnResult:
        del goal, tools, max_steps, conversation_id, system_prompt
        return AgentTurnResult(content="Invented answer without retrieval.", steps=1)


def _tool(
    hits: Sequence[ScoredChunk],
    channel: RetrievalCitationChannel,
) -> RetrieveKnowledgeTool:
    return RetrieveKnowledgeTool(
        _StubRewriteRetrieve(hits),
        channel,
        retrieval_limit=5,
        max_input_length=2000,
    )


def test_agent_grounded_ask_retrieve_then_answer_returns_citations() -> None:
    hit = _hit()
    channel = RetrievalCitationChannel()
    use_case = AskKnowledgeWithAgent(
        _RetrieveThenAnswerAgent(),
        _tool((hit,), channel),
        channel,
        max_steps=8,
        max_input_length=2000,
    )

    response = use_case.execute(AskRequest(query="How do I restart the worker?"))

    assert response.answer == "Restart the worker using the runbook steps."
    assert response.citations == build_citations((hit,))
    assert response.run is not None
    assert response.run.outcome == "success"
    assert response.run.citation_count == 1


def test_agent_grounded_ask_without_retrieve_is_insufficient() -> None:
    channel = RetrievalCitationChannel()
    use_case = AskKnowledgeWithAgent(
        _AnswerWithoutRetrieveAgent(),
        _tool((_hit(),), channel),
        channel,
        max_steps=8,
        max_input_length=2000,
    )

    response = use_case.execute(AskRequest(query="How do I restart the worker?"))

    assert response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
    assert response.citations == ()
    assert response.run is not None
    assert response.run.outcome == "insufficient"


def test_agent_grounded_ask_empty_retrieve_hits_is_insufficient() -> None:
    channel = RetrievalCitationChannel()

    class _RetrieveEmptyThenAnswer(_RetrieveThenAnswerAgent):
        pass

    use_case = AskKnowledgeWithAgent(
        _RetrieveEmptyThenAnswer(),
        _tool((), channel),
        channel,
        max_steps=8,
        max_input_length=2000,
    )

    response = use_case.execute(AskRequest(query="obscure topic"))

    assert response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
    assert response.citations == ()
    assert response.run is not None
    assert response.run.outcome == "insufficient"


def test_agent_grounded_ask_system_prompt_requires_retrieve() -> None:
    channel = RetrievalCitationChannel()
    agent = _RetrieveThenAnswerAgent()
    use_case = AskKnowledgeWithAgent(
        agent,
        _tool((_hit(),), channel),
        channel,
        max_steps=8,
        max_input_length=2000,
    )

    use_case.execute(AskRequest(query="How do I restart?"))

    assert agent.system_prompts
    prompt = agent.system_prompts[0]
    assert prompt is not None
    assert "knowledge.retrieve" in prompt
