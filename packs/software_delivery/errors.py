"""Pack-local validation errors for the Software Delivery pack."""

from domain.errors import DomainValidationError, ToolArgumentValidationError


class GoogleDriveExportValidationError(ToolArgumentValidationError):
    """Invalid caller arguments for Software Delivery Google Drive export."""


class XrayExportValidationError(ToolArgumentValidationError):
    """Invalid caller arguments for Software Delivery Xray test creation."""


class OrchestrationValidationError(DomainValidationError):
    """Invalid Software Delivery chat tool selection."""
