"""RetrieveKnowledgeTool: typed query in, context out, citations via side channel."""

from collections.abc import Mapping, Sequence

import pytest

from application.citations import build_citations
from application.contracts import RetrieveRequest, RewriteRetrieveResponse
from application.retrieval_citation_channel import RetrievalCitationChannel
from application.retrieve_knowledge_tool import (
    RETRIEVE_KNOWLEDGE_TOOL_NAME,
    RetrieveKnowledgeTool,
)
from domain.errors import ToolArgumentValidationError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)


def _hit(
    *,
    source_id: str = "doc-1",
    content: str = "restart the worker process",
    index: int = 3,
    score: float = 0.9,
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
        score=score,
    )


class _StubRewriteRetrieve:
    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = hits
        self.requests: list[RetrieveRequest] = []

    def execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse:
        self.requests.append(request)
        return RewriteRetrieveResponse(
            original_query=request.query,
            rewritten_query=f"rewritten:{request.query}",
            hits=self._hits,
        )


def test_retrieve_tool_returns_context_and_drains_typed_citations() -> None:
    hit = _hit()
    channel = RetrievalCitationChannel()
    rewrite = _StubRewriteRetrieve((hit,))
    tool = RetrieveKnowledgeTool(
        rewrite,
        channel,
        retrieval_limit=5,
        max_input_length=1000,
    )

    context = tool.run({"query": "how do I restart?"})

    assert tool.name == RETRIEVE_KNOWLEDGE_TOOL_NAME
    assert "restart the worker process" in context
    assert "doc-1" in context
    assert channel.drain() == build_citations((hit,))
    assert channel.drain() == ()
    assert [r.query for r in rewrite.requests] == ["how do I restart?"]
    assert rewrite.requests[0].retrieval_limit == 5


def test_retrieve_tool_rejects_blank_query_before_retrieve() -> None:
    rewrite = _StubRewriteRetrieve((_hit(),))
    tool = RetrieveKnowledgeTool(
        rewrite,
        RetrievalCitationChannel(),
        retrieval_limit=5,
        max_input_length=1000,
    )

    with pytest.raises(ToolArgumentValidationError, match="query"):
        tool.run({"query": "   "})

    assert rewrite.requests == []


def test_retrieve_tool_rejects_oversized_query_before_retrieve() -> None:
    rewrite = _StubRewriteRetrieve((_hit(),))
    tool = RetrieveKnowledgeTool(
        rewrite,
        RetrievalCitationChannel(),
        retrieval_limit=5,
        max_input_length=10,
    )

    with pytest.raises(ToolArgumentValidationError, match="query"):
        tool.run({"query": "x" * 11})

    assert rewrite.requests == []


def test_retrieve_tool_records_empty_hits_without_inventing_citations() -> None:
    channel = RetrievalCitationChannel()
    tool = RetrieveKnowledgeTool(
        _StubRewriteRetrieve(()),
        channel,
        retrieval_limit=5,
        max_input_length=1000,
    )

    context = tool.run({"query": "nothing relevant"})

    assert isinstance(context, str) and context.strip()
    assert channel.drain() == ()
