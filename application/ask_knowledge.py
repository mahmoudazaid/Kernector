"""Grounded ask: retrieve context, hold the policy, optionally add a task prompt."""

from collections.abc import Mapping, Sequence
import logging

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
from application.input_safety import reject_unsafe_query
from application.observability import current_request_id, log_operation
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from domain.knowledge import ScoredChunk
from domain.models import Message, PromptVariant
from domain.ports import PromptRepository

logger = logging.getLogger(__name__)


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
        max_input_length: int,
        keep_retrieved_hits: bool = False,
    ) -> None:
        self._rewrite_and_retrieve = rewrite_and_retrieve
        self._ask_service = ask_service
        self._prompt_repository = prompt_repository
        self._default_retrieval_limit = default_retrieval_limit
        self._relevance_threshold = relevance_threshold
        self._max_input_length = max_input_length
        self._keep_retrieved_hits = keep_retrieved_hits

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
            clears it, a fixed insufficient-knowledge answer with empty
            citations; the model is not called, and ``run`` still carries
            retrieval/rewrite/count metadata (``hit_count=0``,
            ``citation_count=0``, ``query_rewritten``).

        Raises:
            ApplicationValidationError: ``query`` or a ``history`` message
                exceeds ``max_input_length``, or a query fails the
                platform/pack input-safety reject rules.
            UnknownPromptError: ``prompt_key`` is set but not in the repository.
            ProviderError: Rewrite, embedding, or chat provider failed.
            VectorStoreError: Vector-store search failed.
            QueryRewriteFailure: Query rewrite failed before retrieval.
        """
        try:
            return self._execute(request, settings)
        except ApplicationValidationError:
            raise
        except Exception as error:
            log_operation(
                logger,
                operation="ask",
                outcome="error",
                level=logging.ERROR,
                error_type=type(error).__name__,
                prompt_key=request.prompt_key,
            )
            raise

    def _execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        if len(request.query) > self._max_input_length:
            raise ApplicationValidationError(
                f"query must be at most {self._max_input_length} characters, "
                f"got {len(request.query)}"
            )
        for index, message in enumerate(request.history):
            if len(message.content) > self._max_input_length:
                raise ApplicationValidationError(
                    f"history[{index}] content must be at most "
                    f"{self._max_input_length} characters, "
                    f"got {len(message.content)}"
                )
        task = self._resolve_variant(request.prompt_key)
        extras = () if task is None else task.extra_reject_patterns
        reject_unsafe_query(request.query, extra_patterns=extras)
        for message in request.history:
            reject_unsafe_query(message.content, extra_patterns=extras)
        limit = request.retrieval_limit or self._default_retrieval_limit
        retrieved = self._rewrite_and_retrieve.execute(
            RetrieveRequest(query=request.query, retrieval_limit=limit)
        )

        hits = self._relevant(retrieved.hits)
        if not hits:
            log_operation(
                logger,
                operation="ask",
                outcome="insufficient",
                hit_count=0,
                prompt_key=request.prompt_key,
            )
            return AskResponse(
                answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
                citations=(),
                run=RunMeta(
                    request_id=current_request_id(),
                    outcome="insufficient",
                    hit_count=0,
                    query_rewritten=retrieved.was_rewritten,
                    citation_count=0,
                    prompt_key=request.prompt_key,
                ),
            )

        prelude = [*request.history, _context_message(hits)]
        if task is not None:
            prelude.append(Message(role="user", content=task.system))

        result = self._ask_service.ask(
            GROUNDED_RAG_SYSTEM,
            request.query,
            settings=settings,
            history=prelude,
        )
        source_type = _source_types(hits)
        citations = build_citations(hits)
        run = RunMeta(
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
            settings=result.settings,
            request_id=current_request_id(),
            outcome="success",
            hit_count=len(hits),
            query_rewritten=retrieved.was_rewritten,
            citation_count=len(citations),
            prompt_key=request.prompt_key,
            source_type=source_type,
        )
        log_operation(
            logger,
            operation="ask",
            outcome="success",
            hit_count=len(hits),
            source_type=source_type,
            prompt_key=request.prompt_key,
            model=run.model,
            latency_ms=run.latency_ms,
            prompt_tokens=None if run.usage is None else run.usage.prompt_tokens,
            completion_tokens=(
                None if run.usage is None else run.usage.completion_tokens
            ),
            total_tokens=None if run.usage is None else run.usage.total_tokens,
        )
        return AskResponse(
            answer=result.content,
            citations=citations,
            run=run,
        )

    def _relevant(self, hits: Sequence[ScoredChunk]) -> tuple[ScoredChunk, ...]:
        """Drop hits the store ranked but that are not close enough to be evidence.

        Retrieval is top-k by cosine similarity, so a non-empty store returns
        ``k`` chunks for *any* query, however unrelated. Treating "the store
        returned rows" as "we have evidence" is what makes a RAG system answer
        confidently from noise; the threshold is what makes the
        insufficient-knowledge path reachable in production rather than only
        against an empty collection.

        When ``keep_retrieved_hits`` is true (Hybrid mode), raw cosine
        eligibility was already applied before fusion; fused ranking scores are
        kept as already-qualified evidence.
        """
        if self._keep_retrieved_hits:
            return tuple(hits)
        return tuple(hit for hit in hits if hit.score >= self._relevance_threshold)

    def _resolve_variant(self, prompt_key: str | None) -> PromptVariant | None:
        """Resolve the optional task prompt before spending a retrieval call."""
        if prompt_key is None:
            return None
        variant = self._prompt_repository.all().get(prompt_key)
        if variant is None:
            raise UnknownPromptError(f"Unknown prompt key {prompt_key!r}")
        return variant


def _source_types(hits: Sequence[ScoredChunk]) -> str | None:
    """Sorted unique source_type values from hits, or ``None`` when empty."""
    types = sorted({hit.chunk.reference.source_type for hit in hits})
    if not types:
        return None
    return ",".join(types)


def _defang(text: str) -> str:
    """Neutralise context delimiters so stored text cannot close the block early."""
    return text.replace(CONTEXT_OPEN, "<«BEGIN_RETRIEVED_CONTEXT»>").replace(
        CONTEXT_CLOSE, "<«END_RETRIEVED_CONTEXT»>"
    )


def _context_message(hits: Sequence[ScoredChunk]) -> Message:
    """Wrap retrieved chunks in the delimiters the policy names as untrusted."""
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
    return Message(role="user", content="\n".join(lines))
