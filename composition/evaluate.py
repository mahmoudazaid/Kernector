"""Offline eval composition: BM25 retrieve, identity rewrite, no live providers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from application.ask_knowledge import AskKnowledge
from application.ask_service import AskService
from application.chunking import chunk_document
from application.errors import ApplicationValidationError, ConfigurationError
from application.evaluate_knowledge import EvaluateKnowledge
from application.evaluation_contracts import (
    EVAL_SCHEMA_VERSION,
    EvalCase,
    EvalCitationLabel,
)
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from composition.container import build_invoke_tool, load_runtime_settings
from composition.correlated_ask import CorrelatedAsk
from composition.errors import KnowledgeLoadError
from composition.tool_augmented_ask import ToolAugmentedAsk
from domain.knowledge import EmbeddedChunk
from domain.models import PromptVariant
from infrastructure.config import DomainToolSettings, Settings
from infrastructure.eval.constant_vector import ConstantVectorAdapter
from infrastructure.eval.corpus import EvalCorpusError, load_eval_corpus
from infrastructure.eval.deterministic_chat import DeterministicChatModel
from infrastructure.eval.identity_rewriter import IdentityQueryRewriter
from infrastructure.lexical.bm25 import Bm25LexicalIndex

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = _PROJECT_ROOT / "data" / "eval"
EVAL_CORPUS_PATH = EVAL_DIR / "corpus.json"
EVAL_CASES_PATH = EVAL_DIR / "cases.json"

_CASE_KEYS = frozenset(
    {
        "id",
        "case_class",
        "kind",
        "query",
        "k",
        "expected_source_ids",
        "expected_answer_mode",
        "expected_citations",
        "tool_name",
        "arguments",
        "expected_tool_result",
    }
)
_LABEL_KEYS = frozenset({"source_id", "source_type", "chunk_index"})
_FILE_KEYS = frozenset({"schema_version", "cases"})


class _EmptyPrompts:
    """Prompt repository with no task prompts."""

    def all(self) -> Mapping[str, PromptVariant]:
        return {}

    def default_key(self) -> str | None:
        return None


class _DisabledPackRunner:
    """Fails if pack-off fallthrough accidentally invokes tools."""

    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
    ) -> object:
        del target, generate_tests, output_style
        raise RuntimeError("pack-off runner must not be called")


def load_eval_cases(path: Path | None = None) -> tuple[EvalCase, ...]:
    """Decode and validate eval cases before scoring.

    Args:
        path (Path | None): JSON object with ``schema_version`` and ``cases``.
            Defaults to ``EVAL_CASES_PATH``.

    Returns:
        tuple[EvalCase, ...]: Validated cases in file order.

    Raises:
        KnowledgeLoadError: Missing file or invalid JSON text.
        ApplicationValidationError: Schema or case contract violation.
    """
    cases_path = path if path is not None else EVAL_CASES_PATH
    try:
        text = cases_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise KnowledgeLoadError(f"eval cases not found: {cases_path}") from error
    except OSError as error:
        raise KnowledgeLoadError(f"eval cases unreadable: {cases_path}") from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ApplicationValidationError("eval cases are not valid JSON") from error
    if not isinstance(payload, dict):
        raise ApplicationValidationError(
            f"eval cases root must be an object, got {type(payload).__name__}"
        )
    unknown = set(payload) - _FILE_KEYS
    if unknown:
        raise ApplicationValidationError("eval cases file has unknown fields")
    if payload.get("schema_version") != EVAL_SCHEMA_VERSION:
        raise ApplicationValidationError(
            "eval cases schema_version must be kernector.eval.v1"
        )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ApplicationValidationError("eval cases must be a JSON array")
    return tuple(_case_from_mapping(item, index) for index, item in enumerate(raw_cases))


def build_evaluate_knowledge(
    settings: Settings | None = None,
    *,
    corpus_path: Path | None = None,
) -> EvaluateKnowledge:
    """Wire an unconditionally offline eval use case.

    Never reads ``OPENROUTER_API_KEY`` to choose behavior. Retrieval is
    BM25-only on an in-memory index populated from the eval corpus.

    Args:
        settings (Settings | None): Runtime settings for chunking and limits.
            Loaded through ``load_runtime_settings`` when omitted.
        corpus_path (Path | None): Eval corpus JSON. Defaults to
            ``EVAL_CORPUS_PATH``.

    Returns:
        EvaluateKnowledge: Use case ready for ``execute``.

    Raises:
        KnowledgeLoadError: Corpus file cannot be loaded.
        ConfigurationError: Settings cannot be loaded, or invoke wiring fails
            in a way that is not treated as tool unavailability.
        ApplicationValidationError: Chunking the corpus fails.
    """
    if settings is None:
        settings = load_runtime_settings()
    documents = _load_corpus(corpus_path if corpus_path is not None else EVAL_CORPUS_PATH)
    lexical = Bm25LexicalIndex()
    adapter = ConstantVectorAdapter()
    embedded: list[EmbeddedChunk] = []
    for document in documents:
        for chunk in chunk_document(
            document,
            chunk_size=settings.chunking.chunk_size,
            chunk_overlap=settings.chunking.chunk_overlap,
        ):
            embedded.append(
                EmbeddedChunk(chunk=chunk, vector=adapter.vector_for(chunk.content))
            )
    lexical.upsert(embedded)
    retrieve = RetrieveKnowledge(
        None,
        None,
        max_input_length=settings.max_input_length,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=1.0,
    )
    rewrite_and_retrieve = RewriteAndRetrieveKnowledge(
        IdentityQueryRewriter(),
        retrieve,
        max_input_length=settings.max_input_length,
    )
    chat = DeterministicChatModel()
    ask = AskKnowledge(
        rewrite_and_retrieve,
        AskService(chat),
        _EmptyPrompts(),
        default_retrieval_limit=settings.retrieval.limit,
        relevance_threshold=settings.retrieval.relevance_threshold,
        max_input_length=settings.max_input_length,
        keep_retrieved_hits=True,
    )
    pack_off_ask = CorrelatedAsk(
        ToolAugmentedAsk(
            ask,
            select=lambda _query: None,
            runner=_DisabledPackRunner(),
            pack_id=None,
        )
    )
    pack_on = replace(
        settings,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    try:
        invoke = build_invoke_tool(pack_on, chat_model=chat)
    except ConfigurationError:
        invoke = None
    return EvaluateKnowledge(
        retrieve=retrieve,
        ask=ask,
        ask_pack_off=pack_off_ask,
        invoke=invoke,
    )


def _load_corpus(path: Path) -> tuple[object, ...]:
    try:
        return load_eval_corpus(path)
    except EvalCorpusError as error:
        raise KnowledgeLoadError(str(error)) from error


def _case_from_mapping(value: object, index: int) -> EvalCase:
    if not isinstance(value, dict):
        raise ApplicationValidationError(
            f"eval case {index} must be an object, got {type(value).__name__}"
        )
    unknown = set(value) - _CASE_KEYS
    if unknown:
        raise ApplicationValidationError(f"eval case {index} has unknown fields")
    payload = dict(value)
    citations = payload.get("expected_citations")
    if citations is not None:
        if not isinstance(citations, list):
            raise ApplicationValidationError(
                f"eval case {index} expected_citations must be an array"
            )
        payload["expected_citations"] = tuple(
            _label_from_mapping(item, index, label_index)
            for label_index, item in enumerate(citations)
        )
    try:
        return EvalCase(**payload)
    except TypeError as error:
        raise ApplicationValidationError(f"eval case {index} is invalid") from error


def _label_from_mapping(
    value: object, case_index: int, label_index: int
) -> EvalCitationLabel:
    if not isinstance(value, dict):
        raise ApplicationValidationError(
            f"eval case {case_index} expected_citations[{label_index}] must be "
            "an object"
        )
    unknown = set(value) - _LABEL_KEYS
    if unknown:
        raise ApplicationValidationError(
            f"eval case {case_index} expected_citations[{label_index}] has "
            "unknown fields"
        )
    return EvalCitationLabel(
        source_id=value["source_id"],
        source_type=value["source_type"],
        chunk_index=value.get("chunk_index"),
    )
