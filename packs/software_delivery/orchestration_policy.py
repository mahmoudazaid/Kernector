"""Software Delivery orchestration constants and chain policy."""

from __future__ import annotations

from enum import StrEnum

RISK_SCORE_TOOL = "software_delivery.risk_score"
GENERATE_TEST_CASES_TOOL = "software_delivery.generate_test_cases"
EXPORT_TEST_CASES_MARKDOWN_TOOL = "software_delivery.export_test_cases_markdown"


class SoftwareDeliveryIntent(StrEnum):
    """Ordered tool chains starting with risk scoring."""

    RISK_SCORE = "risk_score"
    RISK_SCORE_GENERATE_TESTS = "risk_score_generate_test_cases"
    RISK_SCORE_GENERATE_EXPORT = (
        "risk_score_generate_test_cases_export_markdown"
    )


_CHAIN_BY_INTENT: dict[SoftwareDeliveryIntent, tuple[str, ...]] = {
    SoftwareDeliveryIntent.RISK_SCORE: (RISK_SCORE_TOOL,),
    SoftwareDeliveryIntent.RISK_SCORE_GENERATE_TESTS: (
        RISK_SCORE_TOOL,
        GENERATE_TEST_CASES_TOOL,
    ),
    SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT: (
        RISK_SCORE_TOOL,
        GENERATE_TEST_CASES_TOOL,
        EXPORT_TEST_CASES_MARKDOWN_TOOL,
    ),
}

_SUMMARY_BY_INTENT: dict[SoftwareDeliveryIntent, str] = {
    SoftwareDeliveryIntent.RISK_SCORE: (
        "Scored software-delivery risk from the evidence bundle."
    ),
    SoftwareDeliveryIntent.RISK_SCORE_GENERATE_TESTS: (
        "Scored risk and generated test cases from the evidence bundle."
    ),
    SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT: (
        "Scored risk, generated test cases, and exported Markdown."
    ),
}


def tool_chain(intent: SoftwareDeliveryIntent) -> tuple[str, ...]:
    """Return tool names in strict execution order for ``intent``."""
    return _CHAIN_BY_INTENT[intent]


def orchestration_summary(intent: SoftwareDeliveryIntent) -> str:
    """Return the deterministic summary string for ``intent``."""
    return _SUMMARY_BY_INTENT[intent]
