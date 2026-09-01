"""Tests for Software Delivery requirements analysis contracts."""

import pytest

from packs.software_delivery.errors import RequirementsAnalysisValidationError
from packs.software_delivery.limits import MAX_REQUIREMENTS_CHARS
from packs.software_delivery.requirements_analysis_contracts import (
    AnalyzeRequirementsRequest,
)


@pytest.mark.parametrize(
    "requirements",
    [
        "",
        "   ",
        42,
        "x" * (MAX_REQUIREMENTS_CHARS + 1),
    ],
)
def test_analyze_requirements_request_rejects_invalid_requirements(
    requirements: object,
) -> None:
    with pytest.raises(RequirementsAnalysisValidationError):
        AnalyzeRequirementsRequest(requirements)  # type: ignore[arg-type]
