"""Pack-local validation errors for the Software Delivery pack."""

from domain.errors import DomainValidationError, ToolArgumentValidationError


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
