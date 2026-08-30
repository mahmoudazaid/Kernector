"""Grounded ask: retrieve context, compose policy, optionally add a task prompt."""

from collections.abc import Mapping, Sequence

from application.citations import build_citations
from application.contracts import AskRequest, AskResponse, RetrieveRequest
from application.errors import ApplicationValidationError
from application.grounded_rag_policy import (
    DEFAULT_RETRIEVAL_LIMIT,
    GROUNDED_RAG_SYSTEM,
    INSUFFICIENT_KNOWLEDGE_ANSWER,
)
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from domain.knowledge import ScoredChunk
from domain.model_settings import SETTINGS
from domain.models import AskResult, Message
from domain.ports import ChatModel, PromptRepository


class UnknownPromptError(ApplicationValidationError):
    """``AskRequest.prompt_key`` does not match any configured task prompt."""


class AskKnowledge:
    """Orchestrates general grounded chat with optional task-prompt Modes."""

    def __init__(
        self,
        rewrite_and_retrieve: RewriteAndRetrieveKnowledge,
        chat_model: ChatModel,
        prompt_repository: PromptRepository,
    ) -> None:
        self._rewrite_and_retrieve = rewrite_and_retrieve
        self._chat_model = chat_model
        self._prompt_repository = prompt_repository

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Retrieve, compose the grounded system prompt, and answer.

        Args:
            request: Validated ask contract (optional ``prompt_key``, query, …).
            settings: Optional chat generation settings recognized by the domain.

        Returns:
            Model answer with citations derived from retrieval hits.

        Raises:
            UnknownPromptError: ``prompt_key`` is set but not in the repository.
        """
        task_system = self._resolve_task_system(request.prompt_key)
        limit = (
            request.retrieval_limit
            if request.retrieval_limit is not None
            else DEFAULT_RETRIEVAL_LIMIT
        )
        retrieved = self._rewrite_and_retrieve.execute(
            RetrieveRequest(query=request.query, retrieval_limit=limit)
        )
        hits = retrieved.hits
        if not hits:
            return AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER, citations=())

        system = _compose_system(hits, task_system=task_system)
        conversation = [*request.history, Message(role="user", content=request.query)]
        result: AskResult = self._chat_model.complete(
            system, conversation, _allowed(settings)
        )
        return AskResponse(answer=result.content, citations=build_citations(hits))

    def _resolve_task_system(self, prompt_key: str | None) -> str | None:
        if prompt_key is None:
            return None
        prompts = self._prompt_repository.all()
        variant = prompts.get(prompt_key)
        if variant is None:
            raise UnknownPromptError(f"Unknown prompt key {prompt_key!r}")
        return variant.system


def _compose_system(
    hits: Sequence[ScoredChunk],
    *,
    task_system: str | None,
) -> str:
    parts = [GROUNDED_RAG_SYSTEM, _format_retrieved_context(hits)]
    if task_system is not None:
        parts.append(task_system)
    return "\n\n".join(parts)


def _format_retrieved_context(hits: Sequence[ScoredChunk]) -> str:
    if not hits:
        return "Retrieved context:\n(none)"
    lines = ["Retrieved context:"]
    for hit in hits:
        ref = hit.chunk.reference
        title = hit.chunk.metadata.title or ""
        lines.append(
            f"- source_id={ref.source_id} source_type={ref.source_type}"
            f" title={title!r} chunk_index={hit.chunk.index}\n"
            f"  {hit.chunk.content}"
        )
    return "\n".join(lines)


def _allowed(settings: Mapping[str, object] | None) -> dict[str, object]:
    valid_keys = {s.key for s in SETTINGS}
    return {k: v for k, v in (settings or {}).items() if k in valid_keys}
