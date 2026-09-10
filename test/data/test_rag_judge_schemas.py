"""Committed Judge JSON Schemas reject extra fields and match generated reports."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from application.evaluate_rag import EvaluateRag, rag_judge_report_to_csv, rag_judge_report_to_dict
from application.evaluation_contracts import EvalCase, EvalCitationLabel
from application.observed_rag import AnswerModelMetadata, RagObservation
from application.rag_judge_contracts import (
    CSV_HEADERS,
    AnswerRunMetadata,
    JudgeMetadata,
    RagJudgeFingerprints,
    RagJudgeThresholds,
)
from application.rag_judge_policy import METRIC_IDS, PROMPT_VERSION
from domain.models import AskResult

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "data" / "eval" / "schema"
CASES_PATH = REPO_ROOT / "data" / "eval" / "cases.json"
BASELINE_PATH = REPO_ROOT / "data" / "eval" / "baselines" / "rag-judge-baseline.json"


def _registry() -> Registry:
    resources = []
    for path in SCHEMA_DIR.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        resources.append((payload["$id"], Resource.from_contents(payload)))
    return Registry().with_resources(resources)


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


class _Judge:
    def complete(self, system, messages, settings):
        del system, messages, settings
        return AskResult(content='{"score": 0.8, "explanation": "ok"}', model="judge")


def _report():
    case = EvalCase(
        id="cite-1",
        case_class="citation_provenance",
        kind="ask",
        query="q",
        k=5,
        expected_answer_mode="grounded",
        expected_source_ids=("doc-a",),
        expected_citations=(EvalCitationLabel("doc-a", "knowledge_document", 0),),
        reference_answer="ref",
        slice="software_delivery",
    )
    observation = RagObservation(
        case_id="cite-1",
        query="q",
        answer="a",
        citations=(),
        retrieved_contexts=(),
        run=None,
        answer_model=AnswerModelMetadata(provider="openrouter", model="answer"),
    )
    fingerprints = RagJudgeFingerprints(
        dataset_hash="d" * 64,
        corpus_hash="c" * 64,
        metric_set=METRIC_IDS,
        judge_provider="openrouter",
        judge_model="judge",
        prompt_version=PROMPT_VERSION,
        answer_provider="openrouter",
        answer_model="answer",
        embedding_model="embed",
        retrieval_limit=5,
        relevance_threshold=0.0,
        hybrid_enabled=True,
        hybrid_alpha=0.5,
        rewriter="openrouter:rewrite",
    )
    return EvaluateRag().execute(
        (case,),
        {case.id: observation},
        _Judge(),
        RagJudgeThresholds(),
        None,
        JudgeMetadata(
            provider="openrouter",
            model="judge",
            prompt_version=PROMPT_VERSION,
            temperature=0,
        ),
        AnswerRunMetadata(provider="openrouter", model="answer"),
        fingerprints,
        execution_mode="fake",
    )


def test_schemas_declare_ids_and_forbid_additional_properties() -> None:
    for name in (
        "rag-judge-report.json",
        "rag-judge-baseline.json",
        "rag-judge-case-extension.json",
        "rag-judge-fingerprints.json",
    ):
        schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        assert schema["$id"].startswith("https://kernector.local/schemas/")
        assert schema["additionalProperties"] is False
        assert "required" in schema


def test_generated_fake_report_matches_schema() -> None:
    report = _report()
    errors = list(_validator("rag-judge-report.json").iter_errors(rag_judge_report_to_dict(report)))
    assert not errors, "; ".join(error.message for error in errors)


def test_csv_headers_match_contract() -> None:
    header = rag_judge_report_to_csv(_report()).splitlines()[0]
    assert header.split(",") == list(CSV_HEADERS)


def test_committed_baseline_matches_schema_and_is_unaccepted() -> None:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    errors = list(_validator("rag-judge-baseline.json").iter_errors(payload))
    assert not errors, "; ".join(error.message for error in errors)
    assert payload["accepted"] is False


def test_ask_cases_include_judge_extension_fields() -> None:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    validator = _validator("rag-judge-case-extension.json")
    ask_cases = [item for item in payload["cases"] if item["kind"] == "ask"]
    assert ask_cases
    for case in ask_cases:
        extension = {
            "slice": case.get("slice", "core"),
            "reference_answer": case["reference_answer"],
        }
        errors = list(validator.iter_errors(extension))
        assert not errors, f"{case['id']}: " + "; ".join(error.message for error in errors)
    slices = {item.get("slice", "core") for item in ask_cases}
    assert "software_delivery" in slices
    classes = {item["case_class"] for item in ask_cases}
    assert "cross_source" in classes
