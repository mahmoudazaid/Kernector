"""Vendor-neutral contracts for creating Xray tests (#199).

Packs build ``XrayTestSpec`` values and read ``XrayTestCreateSchema``
capabilities. Field discovery, custom-field ids, endpoints, and vendor payloads
stay inside the infrastructure adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from domain.errors import ConnectorError

XrayTestKind = Literal["manual", "cucumber"]


@dataclass(frozen=True, slots=True)
class XrayTestStep:
    """One manual step: an action and its optional expected result."""

    action: str
    expected: str = ""


@dataclass(frozen=True, slots=True)
class XrayTestSpec:
    """One test to create, independent of the Xray deployment."""

    title: str
    kind: XrayTestKind
    preconditions: str = ""
    steps: tuple[XrayTestStep, ...] = ()
    gherkin: str = ""
    link_issue_key: str | None = None
    source_issue_key: str | None = None


@dataclass(frozen=True, slots=True)
class XrayTestCreateSchema:
    """Business-level create capabilities of the configured Xray project."""

    project_key: str
    supports_manual: bool
    supports_cucumber: bool
    supports_issue_link: bool


@dataclass(frozen=True, slots=True)
class XrayImportResult:
    """Keys of the tests Xray created, plus how many it rejected."""

    created_keys: tuple[str, ...]
    failed_count: int


class XrayRequiredFieldsError(ConnectorError):
    """The project requires fields the adapter cannot fill; nothing was created.

    ``field_names`` holds the Jira display names of those fields, never values.
    """

    def __init__(self, field_names: tuple[str, ...]) -> None:
        super().__init__("Xray project requires fields that could not be filled")
        self.field_names = field_names
