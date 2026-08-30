"""Grounded ask: retrieve context, hold the policy, optionally add a task prompt."""

from collections.abc import Mapping, Sequence

from application.ask_service import AskService
from application.citations import build_citations
from application.contracts import AskRequest, AskResponse, RetrieveRequest, RunMeta
from application.errors import ApplicationValidationError
from application.grounded_rag_policy import (
    CONTEXT_CLOSE,
    CONTEXT_OPEN,
    GROUNDED_RAG_SYSTEM,
    INSUFFICIENT_KNOWLEDGE_ANSWER,
)
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from domain.knowledge import ScoredChunk
from domain.models import Message
from domain.ports import PromptRepository


class UnknownPromptError(ApplicationValidationError):
    """``AskRequest.prompt_key`` does not match any configured task prompt."""


class AskKnowledge:
    """Orchestrates general grounded chat with optional task-prompt Modes.

    Privilege is tiered, and the tiers are enforced by *placement*, not by
    wording:

    ==========================  ==========================================
    ``GROUNDED_RAG_SYSTEM``     the ``system`` argument, alone
    retrieved chunks            a delimited message, marked untrusted
    optional task prompt        a message after the context
    ``AskRequest.query``        the final user message
    ==========================  ==========================================

    Retrieved document text is attacker-influenceable — anyone who can get a
    document ingested can choose its words. A pack prompt is author-supplied but
    still lower-trust than platform policy. Neither is concatenated into the
    system string, so neither can impersonate the policy that constrains it.

    Generation goes through ``AskService`` rather than ``ChatModel`` directly,
    so the domain settings allowlist is applied in exactly one place.
    """

    def __init__(
        self,
        rewrite_and_retrieve: RewriteAndRetrieveKnowledge,
        ask_service: AskService,
        prompt_repository: PromptRepository,
        *,
        default_retrieval_limit: int,
        relevance_threshold: float,
    ) -> None:
        self._rewrite_and_retrieve = rewrite_and_retrieve
        self._ask_service = ask_service
        self._prompt_repository = prompt_repository
        self._default_retrieval_limit = default_retrieval_limit
        self._relevance_threshold = relevance_threshold

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Retrieve, compose the tiered conversation, and answer.

        Args:
            request: Validated ask contract (optional ``prompt_key``, query, …).
                ``grounding_references`` is not consulted: no retrieval
                narrowing is defined for it yet.
            settings: Optional generation settings. ``AskService`` filters these
                against the domain allowlist before the adapter sees them.

        Returns:
            Model answer with citations from the chunks that cleared the
            relevance threshold, plus ``RunMeta`` for the call. When nothing
            clears it, a fixed insufficient-knowledge answer with no citations
            and ``run=None`` — the model is not called at all.

        Raises:
            UnknownPromptError: ``prompt_key`` is set but not in the repository.
        """
        task_system = self._resolve_task_system(request.prompt_key)
        limit = request.retrieval_limit or self._default_retrieval_limit
        retrieved = self._rewrite_and_retrieve.execute(
            RetrieveRequest(query=request.query, retrieval_limit=limit)
        )

        hits = self._relevant(retrieved.hits)
        if not hits:
            return AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER, citations=())

        prelude = [*request.history, _context_message(hits)]
        if task_system is not None:
            prelude.append(Message(role="user", content=task_system))

        result = self._ask_service.ask(
            GROUNDED_RAG_SYSTEM,
            request.query,
            settings=settings,
            history=prelude,
        )
        return AskResponse(
            answer=result.content,
            citations=build_citations(hits),
            run=RunMeta.from_result(result),
        )

    def _relevant(self, hits: Sequence[ScoredChunk]) -> tuple[ScoredChunk, ...]:
        """Drop hits the store ranked but that are not close enough to be evidence.

        Retrieval is top-k by cosine similarity, so a non-empty store returns
        ``k`` chunks for *any* query, however unrelated. Treating "the store
        returned rows" as "we have evidence" is what makes a RAG system answer
        confidently from noise; the threshold is what makes the
        insufficient-knowledge path reachable in production rather than only
        against an empty collection.
        """
        return tuple(hit for hit in hits if hit.score >= self._relevance_threshold)

    def _resolve_task_system(self, prompt_key: str | None) -> str | None:
        """Resolve the optional task prompt before spending a retrieval call."""
        if prompt_key is None:
            return None
        variant = self._prompt_repository.all().get(prompt_key)
        if variant is None:
            raise UnknownPromptError(f"Unknown prompt key {prompt_key!r}")
        return variant.system


def _context_message(hits: Sequence[ScoredChunk]) -> Message:
    """Wrap retrieved chunks in the delimiters the policy names as untrusted."""
    lines = [CONTEXT_OPEN]
    for hit in hits:
        ref = hit.chunk.reference
        title = hit.chunk.metadata.title or ""
        lines.append(
            f"- source_id={ref.source_id} source_type={ref.source_type}"
            f" title={title!r} chunk_index={hit.chunk.index}\n"
            f"  {hit.chunk.content}"
        )
    lines.append(CONTEXT_CLOSE)
    return Message(role="user", content="\n".join(lines))
