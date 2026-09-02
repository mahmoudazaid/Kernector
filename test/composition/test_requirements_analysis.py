"""Composition-facing requirements-analysis helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from composition import (
    RequirementsAnalysisFindingView,
    RequirementsAnalysisView,
    format_requirements_analysis_answer,
    requirements_analysis_enabled,
)
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
from packs.software_delivery.errors import MissingEvidenceError

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Settings:
    """Duck-typed stand-in: reads ``domain_tools.enabled_packs`` only."""

    def __init__(self, *packs: str) -> None:
        self.domain_tools = SimpleNamespace(enabled_packs=packs)


def test_requirements_analysis_is_disabled_without_the_pack() -> None:
    assert requirements_analysis_enabled(_Settings()) is False
    assert requirements_analysis_enabled(_Settings("other-pack")) is False


def test_requirements_analysis_is_enabled_with_the_pack() -> None:
    assert requirements_analysis_enabled(_Settings("software-delivery")) is True


def test_pack_analyzer_projects_ask_result_onto_view_for_run_meta() -> None:
    """Composition projects AskResult metadata without a new façade type."""
    from composition.requirements_analysis import PackRequirementsAnalyzer
    from domain.models import AskResult, Usage
    from packs.software_delivery.requirements_analysis_contracts import (
        RequirementsAnalysisResult,
    )

    ask_result = AskResult(
        content='{"summary":"ok"}',
        model="proj-model",
        latency_ms=9,
        usage=Usage(total_tokens=3),
        settings={"temperature": 0.0},
    )
    pack_result = RequirementsAnalysisResult(
        summary="ok",
        acceptance_criteria_gaps=(),
        risks=(),
        clarification_questions=(),
        evidence=(),
        ask_result=ask_result,
    )
    analyzer = PackRequirementsAnalyzer(lambda _requirements: pack_result)

    view = analyzer.analyze("Need MFA.")

    assert view.ask_result is ask_result
    # Import RunMeta with the same module identity AskResponse uses (top-level).
    from application.contracts import RunMeta

    assert RunMeta.from_result(view.ask_result) == RunMeta(
        model="proj-model",
        latency_ms=9,
        usage=Usage(total_tokens=3),
        settings={"temperature": 0.0},
    )

    view = RequirementsAnalysisView(
        summary="The story omits lockout.",
        acceptance_criteria_gaps=(
            RequirementsAnalysisFindingView(
                statement="No lockout criterion.",
                references=(SourceReference("SRS-2", "srs"),),
            ),
        ),
        risks=(),
        clarification_questions=(
            RequirementsAnalysisFindingView(
                statement="What is the lockout duration?",
                references=(SourceReference("US-1", "user_story"),),
            ),
        ),
        evidence=(
            ScoredChunk(
                chunk=DocumentChunk(
                    metadata=SourceMetadata(
                        SourceReference("US-1", "user_story"),
                        extra={},
                    ),
                    index=0,
                    content="Users must authenticate with MFA.",
                ),
                score=0.9,
            ),
        ),
    )

    answer = format_requirements_analysis_answer(view)

    assert answer.startswith("The story omits lockout.")
    assert "**Acceptance criteria gaps**" in answer
    assert "No lockout criterion. — `SRS-2` (srs)" in answer
    assert "**Clarification questions**" in answer
    assert "What is the lockout duration? — `US-1` (user_story)" in answer
    assert "**Risks**" not in answer


def test_composition_errors_remain_infrastructure_wrappers_only() -> None:
    """Generic use-case outcomes belong in application, not composition.errors."""
    source = (REPO_ROOT / "composition/errors.py").read_text(encoding="utf-8")
    assert "RequirementsEvidenceUnavailableError" not in source
    assert "InsufficientEvidenceError" not in source
    for name in (
        "KnowledgeLoadError",
        "DocumentUploadError",
        "DocumentOperationError",
        "PartialDocumentOperationError",
    ):
        assert f"class {name}" in source


def test_insufficient_evidence_translation_is_singular_at_composition_edge() -> None:
    container_source = (REPO_ROOT / "composition/container.py").read_text(
        encoding="utf-8"
    )
    assert container_source.count("raise InsufficientEvidenceError") == 1
    assert "MissingEvidenceError" in container_source
    assert "RequirementsEvidenceUnavailableError" not in container_source
    assert issubclass(MissingEvidenceError, Exception)
