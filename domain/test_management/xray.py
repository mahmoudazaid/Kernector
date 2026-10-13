"""Vendor-neutral contracts for creating Xray tests (#199).

Packs build ``XrayTestSpec`` values and read ``XrayTestCreateSchema``
capabilities. Field discovery, custom-field ids, endpoints, and vendor payloads
stay inside the infrastructure adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from domain.errors import ConnectorError

XrayTestKind = Literal["manual", "cucumber"]
XrayCreateWarningReason = Literal["link_not_confirmed", "outline_not_confirmed"]


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
    component: str | None = None
    outline: bool = False


@dataclass(frozen=True, slots=True)
class XrayTestCreateSchema:
    """Business-level create capabilities of the configured Xray project."""

    project_key: str
    supports_manual: bool
    supports_cucumber: bool
    supports_issue_link: bool
    supports_cucumber_outline: bool = False


@dataclass(frozen=True, slots=True)
class XrayCreateWarning:
    """A test was created but Xray did not confirm part of the request."""

    key: str
    reason: XrayCreateWarningReason


@dataclass(frozen=True, slots=True)
class XrayImportResult:
    """Keys of the tests Xray created, plus how many it rejected."""

    created_keys: tuple[str, ...]
    failed_count: int
    warnings: tuple[XrayCreateWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class JiraIssueSummary:
    """Identity of one Jira issue; ``is_test`` follows the adapter's discovered Test type."""

    key: str
    summary: str
    issue_type_id: str
    issue_type_name: str
    is_test: bool


@dataclass(frozen=True, slots=True)
class IssueLookupResult:
    """Outcome of a key lookup.

    ``missing`` holds only keys Jira definitively reported absent. A requested
    key in neither ``found`` nor ``missing`` is unresolved and must never be
    treated as absent.
    """

    found: Mapping[str, JiraIssueSummary] = field(default_factory=dict)
    missing: frozenset[str] = frozenset()


class XrayRequiredFieldsError(ConnectorError):
    """The project requires fields the adapter cannot fill; nothing was created.

    ``field_names`` holds the Jira display names of those fields, never values.
    """

    def __init__(self, field_names: tuple[str, ...]) -> None:
        super().__init__("Xray project requires fields that could not be filled")
        self.field_names = field_names
