"""Software Delivery project contexts (ADR 0011 section 10), registered as data."""

from __future__ import annotations

from dataclasses import dataclass

SOFTWARE_DELIVERY_CONTEXTS: tuple[str, ...] = (
    "business",
    "api_contract",
    "frontend",
    "backend",
    "operations",
    "testing",
    "documentation",
)


@dataclass(frozen=True, slots=True)
class SoftwareDeliveryContextVocabulary:
    """Implements ``domain.project.ports.ContextVocabulary``."""

    contexts: tuple[str, ...] = SOFTWARE_DELIVERY_CONTEXTS
