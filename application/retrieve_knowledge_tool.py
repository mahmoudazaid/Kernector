"""Domain Tool wrapping rewrite-and-retrieve for agentic RAG."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from application.contracts import RetrieveRequest, RewriteRetrieveResponse
from application.grounded_rag_policy import CONTEXT_CLOSE, CONTEXT_OPEN
from application.retrieval_citation_channel import RetrievalCitationChannel
from domain.errors import ToolArgumentValidationError
from domain.knowledge import ScoredChunk

RETRIEVE_KNOWLEDGE_TOOL_NAME = "knowledge.retrieve"
RETRIEVE_KNOWLEDGE_TOOL_DESCRIPTION = (
    "Retrieve grounded knowledge for a natural-language query. "
    "Pass a non-blank query string. Use retrieved context before answering."
)

_EMPTY_CONTEXT = (
    f"{CONTEXT_OPEN}\n"
    "No relevant documents were retrieved for this query.\n"
    f"{CONTEXT_CLOSE}"
)


class RetrieveKnowledgeToolArgs(BaseModel):
    """Typed arguments the model must supply for ``knowledge.retrieve``."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="Natural-language query to retrieve knowledge for")


class _RewriteAndRetrieve(Protocol):
    def execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse: ...


class RetrieveKnowledgeTool:
    """Implements ``domain.ports.Tool`` for rewrite-and-retrieve.

    Returns model-facing context text. Citations are deposited on the injected
    ``RetrievalCitationChannel`` — never encoded for later text recovery.
    """

    args_schema = RetrieveKnowledgeToolArgs

    def __init__(
        self,
        rewrite_and_retrieve: _RewriteAndRetrieve,
        channel: RetrievalCitationChannel,
        *,
        retrieval_limit: int,
        max_input_length: int,
    ) -> None:
        self._rewrite_and_retrieve = rewrite_and_retrieve
        self._channel = channel
        self._retrieval_limit = retrieval_limit
        self._max_input_length = max_input_length

    @property
    def name(self) -> str:
        return RETRIEVE_KNOWLEDGE_TOOL_NAME

    @property
    def description(self) -> str:
        return RETRIEVE_KNOWLEDGE_TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        """Retrieve for ``arguments['query']``; record hits on the side channel.

        Raises:
            ToolArgumentValidationError: Missing/blank/oversized query.
        """
        query = _require_query(arguments, max_input_length=self._max_input_length)
        response = self._rewrite_and_retrieve.execute(
            RetrieveRequest(query=query, retrieval_limit=self._retrieval_limit)
        )
        hits = tuple(response.hits)
        self._channel.record(hits)
        if not hits:
            return _EMPTY_CONTEXT
        return _format_context(hits)


def _require_query(
    arguments: Mapping[str, object],
    *,
    max_input_length: int,
) -> str:
    raw = arguments.get("query")
    if not isinstance(raw, str) or not raw.strip():
        raise ToolArgumentValidationError("query must be a non-empty string")
    query = raw.strip()
    if len(query) > max_input_length:
        raise ToolArgumentValidationError(
            f"query must be at most {max_input_length} characters, "
            f"got {len(query)}"
        )
    return query


def _defang(text: str) -> str:
    return text.replace(CONTEXT_OPEN, "<«BEGIN_RETRIEVED_CONTEXT»>").replace(
        CONTEXT_CLOSE, "<«END_RETRIEVED_CONTEXT»>"
    )


def _format_context(hits: Sequence[ScoredChunk]) -> str:
    lines = [CONTEXT_OPEN]
    for hit in hits:
        ref = hit.chunk.reference
        title = _defang(hit.chunk.metadata.title or "")
        source_id = _defang(ref.source_id)
        source_type = _defang(ref.source_type)
        content = _defang(hit.chunk.content)
        lines.append(
            f"- source_id={source_id} source_type={source_type}"
            f" title={title!r} chunk_index={hit.chunk.index}\n"
            f"  {content}"
        )
    lines.append(CONTEXT_CLOSE)
    return "\n".join(lines)
