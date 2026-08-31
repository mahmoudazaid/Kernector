"""Pack-local validation errors for Software Delivery risk scoring."""

from domain.errors import ToolArgumentValidationError


class RiskScoreValidationError(ToolArgumentValidationError):
    """Invalid Software Delivery risk assessment input or result."""
