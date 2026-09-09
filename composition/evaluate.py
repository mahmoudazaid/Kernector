"""Offline eval composition: BM25 retrieve, identity rewrite, no live providers."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from application.ask_knowledge import AskKnowledge
from application.ask_service import AskService
from application.chunking import chunk_document
from application.contracts import IngestRequest
from application.errors import ApplicationValidationError, ConfigurationError
from application.evaluate_knowledge import EvaluateKnowledge
from application.evaluate_rag import (
    EvaluateRag,
    parse_rag_judge_baseline,
)
from application.evaluation_contracts import (
    EVAL_SCHEMA_VERSION,
    EvalCase,
    EvalCitationLabel,
)
from application.observability import log_operation
from application.observed_rag import (
    AnswerModelMetadata,
    ObservedRagRunner,
    RagObservation,
    RecordingRewriteAndRetrieve,
    RetrievalRecorder,
)
from application.rag_judge_contracts import (
    AnswerRunMetadata,
    JudgeMetadata,
    RagJudgeBaseline,
    RagJudgeFingerprints,
    RagJudgeReport,
    RagJudgeThresholds,
)
from application.rag_judge_policy import METRIC_IDS, PROMPT_VERSION
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from composition.container import (
    build_chat_model,
    build_ingest_knowledge,
    build_invoke_tool,
    build_prompt_repository,
    build_rewrite_and_retrieve_knowledge,
    build_vector_store,
    load_runtime_settings,
)
from composition.correlated_ask import CorrelatedAsk
from composition.errors import KnowledgeLoadError
from composition.tool_augmented_ask import ToolAugmentedAsk
from domain.errors import ProviderError, VectorStoreError
from domain.knowledge import EmbeddedChunk, SourceDocument
from domain.models import PromptVariant
from domain.ports import ChatModel
from infrastructure.config import (
    ChromaSettings,
    DomainToolSettings,
    Settings,
    judge_complete_kwargs,
    judge_config_ready,
    live_answer_config_ready,
)
from infrastructure.eval.constant_vector import ConstantVectorAdapter
from infrastructure.eval.corpus import EvalCorpusError, load_eval_corpus
from infrastructure.eval.deterministic_chat import DeterministicChatModel
from infrastructure.eval.identity_rewriter import IdentityQueryRewriter
from infrastructure.lexical.bm25 import Bm25LexicalIndex

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = _PROJECT_ROOT / "data" / "eval"
EVAL_CORPUS_PATH = EVAL_DIR / "corpus.json"
EVAL_CASES_PATH = EVAL_DIR / "cases.json"
EVAL_BASELINE_PATH = EVAL_DIR / "baselines" / "rag-judge-baseline.json"
_LIVE_EVAL_COLLECTION = "kernector_eval_judge"
logger = logging.getLogger(__name__)

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
        "slice",
        "reference_answer",
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
    except UnicodeDecodeError as error:
        raise ApplicationValidationError("eval cases are not valid UTF-8") from error
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
        ConfigurationError: Settings cannot be loaded, or invoke wiring fails.
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
    recorder = RetrievalRecorder()
    recording = RecordingRewriteAndRetrieve(rewrite_and_retrieve, recorder)
    chat = DeterministicChatModel()
    ask = AskKnowledge(
        recording,
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
    invoke = build_invoke_tool(pack_on, chat_model=chat)
    observed = ObservedRagRunner(
        ask,
        recorder,
        AnswerModelMetadata(provider="eval", model="eval-offline"),
    )
    return EvaluateKnowledge(
        retrieve=retrieve,
        ask_pack_off=pack_off_ask,
        invoke=invoke,
        observed_rag=observed,
    )


def _load_corpus(path: Path) -> tuple[SourceDocument, ...]:
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


class JudgeSkipped(ConfigurationError):
    """``auto`` cannot run a live Judge; never substituted with fake scores."""


@dataclass(frozen=True, slots=True)
class LiveObservedRagSession:
    """Temp-Chroma live ask runner plus sanitized answer-model metadata.

    Args:
        runner (ObservedRagRunner): Same-run observer over configured RAG.
        answer_meta (AnswerRunMetadata): Effective answer-model identity.
        persist_path (Path): Temporary Chroma directory for this session.
        rewriter (str): Rewriter fingerprint string.
        embedding_model (str): Embedding model id used to ingest the eval corpus.
    """

    runner: ObservedRagRunner
    answer_meta: AnswerRunMetadata
    persist_path: Path
    rewriter: str
    embedding_model: str


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``.

    Args:
        path (Path): File to hash.

    Returns:
        str: Hex digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rag_judge_baseline(path: Path | None = None) -> RagJudgeBaseline | None:
    """Load the committed Judge baseline, if present.

    Args:
        path (Path | None): Baseline JSON. Defaults to ``EVAL_BASELINE_PATH``.

    Returns:
        RagJudgeBaseline | None: Parsed baseline, or ``None`` when missing.

    Raises:
        ApplicationValidationError: File exists but is not a valid baseline.
        KnowledgeLoadError: File cannot be read.
    """
    baseline_path = path if path is not None else EVAL_BASELINE_PATH
    if not baseline_path.is_file():
        return None
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise ApplicationValidationError(
            "rag judge baseline is not valid UTF-8"
        ) from error
    except json.JSONDecodeError as error:
        raise ApplicationValidationError("rag judge baseline is not valid JSON") from error
    except OSError as error:
        raise KnowledgeLoadError(f"rag judge baseline unreadable: {baseline_path}") from error
    if not isinstance(payload, dict):
        raise ApplicationValidationError("rag judge baseline root must be an object")
    return parse_rag_judge_baseline(payload)


def reject_deterministic_answer_model(chat: ChatModel) -> None:
    """Refuse ``DeterministicChatModel`` as a live quality-gate answer model.

    Args:
        chat (ChatModel): Candidate answer model.

    Raises:
        ConfigurationError: ``chat`` is the offline deterministic adapter.
    """
    if isinstance(chat, DeterministicChatModel):
        raise ConfigurationError(
            "live Judge answer model must not be DeterministicChatModel"
        )


def build_judge_chat_model(settings: Settings) -> ChatModel:
    """Construct the Judge ChatModel from ``RAG_JUDGE_*`` only.

    Args:
        settings (Settings): Loaded process settings.

    Returns:
        ChatModel: Judge model. Never the answer-model default.

    Raises:
        ConfigurationError: Judge provider/model/credentials are missing.
    """
    judge = settings.rag_judge
    if not judge.provider or not judge.model:
        raise ConfigurationError(
            "RAG_JUDGE_PROVIDER and RAG_JUDGE_MODEL are required for live Judge"
        )
    if judge.provider == "openrouter":
        config = settings.openrouter
        if judge.base_url:
            config = replace(config, base_url=judge.base_url)
        patched = replace(settings, openrouter=replace(config, model=judge.model))
        return build_chat_model(
            patched, provider="openrouter", model=judge.model, base_url=judge.base_url
        )
    if judge.provider == "ollama":
        config = settings.ollama
        if judge.base_url:
            config = replace(config, base_url=judge.base_url)
        patched = replace(settings, ollama=replace(config, model=judge.model))
        return build_chat_model(
            patched, provider="ollama", model=judge.model, base_url=judge.base_url
        )
    raise ConfigurationError(
        f"RAG_JUDGE_PROVIDER must be openrouter or ollama, got {judge.provider!r}"
    )


def _answer_model_id(settings: Settings) -> str:
    if settings.provider == "ollama":
        return settings.ollama.model or "unknown"
    return settings.openrouter.model or "unknown"


def _rewriter_fingerprint(settings: Settings) -> str:
    model = settings.openrouter.rewrite_model or settings.openrouter.model or "unknown"
    return f"openrouter:{model}"


@contextmanager
def live_observed_rag_session(
    settings: Settings,
    *,
    corpus_path: Path | None = None,
    chat_model: ChatModel | None = None,
):
    """Ingest the eval corpus into a temp Chroma store and yield a live runner.

    Never reads or mutates production ``data/chroma``. Tears down the temp
    directory on exit.

    Args:
        settings (Settings): Production-configured RAG settings.
        corpus_path (Path | None): Eval corpus JSON. Defaults to
            ``EVAL_CORPUS_PATH``.
        chat_model (ChatModel | None): Optional injected answer model.

    Yields:
        LiveObservedRagSession: Runner plus fingerprints inputs.

    Raises:
        ConfigurationError: Deterministic answer model, production Chroma path,
            or provider construction failure.
        KnowledgeLoadError: Eval corpus cannot be loaded.
    """
    try:
        chat = chat_model if chat_model is not None else build_chat_model(settings)
    except ProviderError as error:
        raise ConfigurationError("live Judge answer path failed") from error
    reject_deterministic_answer_model(chat)
    production_chroma = settings.chroma.persist_path.resolve()
    with TemporaryDirectory(prefix="kernector-eval-chroma-") as raw_tmp:
        persist_path = Path(raw_tmp)
        if persist_path.resolve() == production_chroma:
            raise ConfigurationError(
                "live eval Chroma must not use the production persist path"
            )
        eval_settings = replace(
            settings,
            chroma=ChromaSettings(
                persist_path=persist_path,
                collection=_LIVE_EVAL_COLLECTION,
            ),
        )
        try:
            store = build_vector_store(eval_settings)
            ingest = build_ingest_knowledge(eval_settings, vector_store=store)
            documents = _load_corpus(
                corpus_path if corpus_path is not None else EVAL_CORPUS_PATH
            )
            ingest.execute(IngestRequest(documents=documents))
            rewrite = build_rewrite_and_retrieve_knowledge(
                eval_settings, vector_store=store
            )
            recorder = RetrievalRecorder()
            recording = RecordingRewriteAndRetrieve(rewrite, recorder)
            ask = AskKnowledge(
                recording,
                AskService(chat),
                build_prompt_repository(eval_settings),
                default_retrieval_limit=eval_settings.retrieval.limit,
                relevance_threshold=eval_settings.retrieval.relevance_threshold,
                max_input_length=eval_settings.max_input_length,
                keep_retrieved_hits=eval_settings.retrieval.hybrid_enabled,
            )
            answer_meta = AnswerRunMetadata(
                provider=eval_settings.provider,
                model=_answer_model_id(eval_settings),
            )
            runner = ObservedRagRunner(
                ask,
                recorder,
                AnswerModelMetadata(
                    provider=answer_meta.provider, model=answer_meta.model
                ),
            )
        except (ProviderError, VectorStoreError) as error:
            raise ConfigurationError("live Judge answer path failed") from error
        yield LiveObservedRagSession(
            runner=runner,
            answer_meta=answer_meta,
            persist_path=persist_path,
            rewriter=_rewriter_fingerprint(eval_settings),
            embedding_model=eval_settings.openrouter.embedding_model,
        )


def _fingerprints_for(
    settings: Settings,
    *,
    judge_provider: str,
    judge_model: str,
    answer_meta: AnswerRunMetadata,
    rewriter: str,
    embedding_model: str,
    cases_path: Path,
    corpus_path: Path,
) -> RagJudgeFingerprints:
    return RagJudgeFingerprints(
        dataset_hash=sha256_file(cases_path),
        corpus_hash=sha256_file(corpus_path),
        metric_set=METRIC_IDS,
        judge_provider=judge_provider,
        judge_model=judge_model,
        prompt_version=PROMPT_VERSION,
        answer_provider=answer_meta.provider,
        answer_model=answer_meta.model,
        embedding_model=embedding_model,
        retrieval_limit=settings.retrieval.limit,
        relevance_threshold=settings.retrieval.relevance_threshold,
        hybrid_enabled=settings.retrieval.hybrid_enabled,
        hybrid_alpha=settings.retrieval.hybrid_alpha,
        rewriter=rewriter,
    )


def _judge_metadata(settings: Settings, seed_applied: int | None) -> JudgeMetadata:
    judge = settings.rag_judge
    return JudgeMetadata(
        provider=judge.provider or "unconfigured",
        model=judge.model or "unconfigured",
        prompt_version=PROMPT_VERSION,
        temperature=0,
        seed_configured=judge.seed,
        seed_applied=seed_applied,
    )


def run_rag_judge(
    mode: str,
    cases: Sequence[EvalCase],
    *,
    settings: Settings | None = None,
    baseline_path: Path | None = None,
    cases_path: Path | None = None,
    corpus_path: Path | None = None,
    chat_model: ChatModel | None = None,
    judge: ChatModel | None = None,
) -> RagJudgeReport:
    """Run the Judge path for ``live``, ``fake``, or ``auto``.

    Args:
        mode (str): ``live``, ``fake``, or ``auto``.
        cases (Sequence[EvalCase]): Full suite; non-ask kinds are ignored.
        settings (Settings | None): Runtime settings. Loaded when omitted.
        baseline_path (Path | None): Optional baseline override.
        cases_path (Path | None): Cases file used for dataset hash.
        corpus_path (Path | None): Corpus file used for corpus hash and ingest.
        chat_model (ChatModel | None): Optional live answer-model override.
        judge (ChatModel | None): Optional Judge-model override.

    Returns:
        RagJudgeReport: Additive Judge report.

    Raises:
        JudgeSkipped: ``auto`` cannot construct live answer RAG and Judge.
        ConfigurationError: Live construction failed.
        ApplicationValidationError: Baseline file is malformed.
    """
    if settings is None:
        settings = load_runtime_settings()
    dataset = cases_path if cases_path is not None else EVAL_CASES_PATH
    corpus = corpus_path if corpus_path is not None else EVAL_CORPUS_PATH
    baseline = load_rag_judge_baseline(baseline_path)
    thresholds = RagJudgeThresholds()
    if mode == "auto":
        if not live_answer_config_ready(settings) or not judge_config_ready(settings):
            raise JudgeSkipped(
                "auto Judge skipped: live answer RAG and RAG_JUDGE_* are not ready; "
                "refusing to substitute fake scores"
            )
        mode = "live"
    if mode == "fake":
        fake_answer = AnswerRunMetadata(provider="fake", model="ineligible")
        fingerprints = _fingerprints_for(
            settings,
            judge_provider="fake",
            judge_model="ineligible",
            answer_meta=fake_answer,
            rewriter="identity",
            embedding_model="none",
            cases_path=dataset,
            corpus_path=corpus,
        )
        return EvaluateRag().execute(
            cases,
            {},
            DeterministicChatModel(),
            thresholds,
            baseline,
            JudgeMetadata(
                provider="fake",
                model="ineligible",
                prompt_version=PROMPT_VERSION,
                temperature=0,
            ),
            fake_answer,
            fingerprints,
            execution_mode="fake",
        )
    if mode != "live":
        raise ConfigurationError(f"unknown judge mode {mode!r}")
    if not judge_config_ready(settings) and judge is None:
        raise ConfigurationError(
            "RAG_JUDGE_PROVIDER and RAG_JUDGE_MODEL are required for live Judge"
        )
    complete_kwargs, seed_applied = judge_complete_kwargs(settings)
    try:
        judge_model = judge if judge is not None else build_judge_chat_model(settings)
    except ProviderError as error:
        raise ConfigurationError("live Judge could not be constructed") from error
    judge_meta = _judge_metadata(settings, seed_applied)
    with live_observed_rag_session(
        settings, corpus_path=corpus, chat_model=chat_model
    ) as session:
        observations: dict[str, RagObservation] = {}
        observation_errors: dict[str, str] = {}
        for case in cases:
            if case.kind != "ask":
                continue
            try:
                observations[case.id] = session.runner.execute(case)
            except ApplicationValidationError:
                observation_errors[case.id] = "observation_integrity"
                log_operation(
                    logger,
                    operation="judge_observe",
                    outcome="error",
                    error_type="observation_integrity",
                    case_id=case.id,
                )
            except (ProviderError, VectorStoreError) as error:
                observation_errors[case.id] = "judge_error"
                log_operation(
                    logger,
                    operation="judge_observe",
                    outcome="error",
                    error_type=type(error).__name__,
                    case_id=case.id,
                )
        fingerprints = _fingerprints_for(
            settings,
            judge_provider=judge_meta.provider,
            judge_model=judge_meta.model,
            answer_meta=session.answer_meta,
            rewriter=session.rewriter,
            embedding_model=session.embedding_model,
            cases_path=dataset,
            corpus_path=corpus,
        )
        return EvaluateRag().execute(
            cases,
            observations,
            judge_model,
            thresholds,
            baseline,
            judge_meta,
            session.answer_meta,
            fingerprints,
            execution_mode="live",
            judge_settings=complete_kwargs,
            observation_errors=observation_errors,
        )
