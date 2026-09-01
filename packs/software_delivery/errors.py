"""Pack-local validation errors for the Software Delivery pack."""

from domain.errors import DomainValidationError, ProviderError, ToolArgumentValidationError


class RiskScoreValidationError(ToolArgumentValidationError):
    """Invalid Software Delivery risk assessment input or result."""


class AssessmentPromptValidationError(DomainValidationError):
    """Invalid input supplied to the Software Delivery prompt boundary."""


class TestCaseGenerationValidationError(ToolArgumentValidationError):
    """Invalid caller arguments for Software Delivery test-case generation."""

    __test__ = False


class MarkdownExportValidationError(ToolArgumentValidationError):
    """Invalid caller arguments for Software Delivery Markdown export."""


class OrchestrationValidationError(DomainValidationError):
    """Invalid Software Delivery orchestration request or response."""


class RequirementsAnalysisValidationError(DomainValidationError):
    """Invalid caller input for Software Delivery requirements analysis."""


class RequirementsAnalysisOutputError(ProviderError):
    """Invalid or unusable requirements-analysis model output."""


class MissingEvidenceError(DomainValidationError):
    """No retrieval hits cleared the relevance threshold for analysis."""

