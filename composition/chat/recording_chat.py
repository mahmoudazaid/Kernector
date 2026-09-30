"""ChatModel wrapper that records safe RunMeta for tool-turn observability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from application.contracts import RunMeta
from domain.models import AskResult, Message, Usage
from domain.ports import ChatModel


class RecordingChatModel:
    """Delegate to an inner ``ChatModel`` and keep a safe metadata snapshot.

    Used so tool chains that call the model through the opaque invoke boundary
    can still surface latency / tokens on ``ToolRunOutcome.run`` without retaining
    model response bodies or putting metadata into tool JSON payloads.

    By default at most one model call may be recorded between ``clear`` /
    ``consume`` cycles (deterministic #170 tool runs). With ``accumulate=True``
    (agent loop), successive calls and ``record`` observations merge latency and
    token counts so ReAct turns are not under-reported.
    """

    def __init__(self, inner: ChatModel, *, accumulate: bool = False) -> None:
        self._inner = inner
        self._accumulate = accumulate
        self._last: RunMeta | None = None

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        if self._last is not None and not self._accumulate:
            raise RuntimeError(
                "RecordingChatModel already recorded a model call for this run"
            )
        result = self._inner.complete(system, messages, settings)
        self.record(RunMeta.from_result(result))
        return result

    def record(self, meta: RunMeta) -> None:
        """Merge or store safe metadata from a model call outside ``complete``.

        Used by the agent-loop LangChain wrapper so ReAct invokes contribute to
        the same ``ToolRunOutcome.run`` ledger as opaque tool ChatModel calls.
        """
        if self._last is None:
            self._last = meta
            return
        if not self._accumulate:
            raise RuntimeError(
                "RecordingChatModel already recorded a model call for this run"
            )
        self._last = _merge_run_meta(self._last, meta)

    def clear(self) -> None:
        """Discard any recorded metadata without returning it."""
        self._last = None

    def consume(self) -> RunMeta | None:
        """Return and clear the recorded safe metadata (if any)."""
        last, self._last = self._last, None
        return last


def _merge_run_meta(left: RunMeta, right: RunMeta) -> RunMeta:
    return RunMeta(
        model=right.model or left.model,
        latency_ms=_sum_optional_int(left.latency_ms, right.latency_ms),
        usage=_merge_usage(left.usage, right.usage),
        settings=dict(right.settings) if right.settings else dict(left.settings),
        request_id=right.request_id or left.request_id,
        outcome=right.outcome or left.outcome,
        hit_count=right.hit_count if right.hit_count is not None else left.hit_count,
        query_rewritten=(
            right.query_rewritten
            if right.query_rewritten is not None
            else left.query_rewritten
        ),
        citation_count=(
            right.citation_count
            if right.citation_count is not None
            else left.citation_count
        ),
        pack=right.pack or left.pack,
        path=right.path or left.path,
        prompt_key=right.prompt_key or left.prompt_key,
        source_type=right.source_type or left.source_type,
        tools=tuple(left.tools) + tuple(right.tools),
        error_type=right.error_type or left.error_type,
    )


def _sum_optional_int(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


def _merge_usage(left: Usage | None, right: Usage | None) -> Usage | None:
    if left is None:
        return right
    if right is None:
        return left
    return Usage(
        prompt_tokens=_sum_optional_int(left.prompt_tokens, right.prompt_tokens),
        completion_tokens=_sum_optional_int(
            left.completion_tokens, right.completion_tokens
        ),
        total_tokens=_sum_optional_int(left.total_tokens, right.total_tokens),
        cost=_sum_optional_float(left.cost, right.cost),
    )


def _sum_optional_float(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return (left or 0.0) + (right or 0.0)
