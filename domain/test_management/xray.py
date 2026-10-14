"""Vendor-neutral contracts for creating (#199) and updating (#398) Xray tests.

Packs build ``XrayTestSpec`` values and read ``XrayTestCreateSchema``
capabilities; updates read ``XrayTestDetails`` and send ``XrayTestPatch``. Field discovery, custom-field ids, endpoints, and vendor payloads
stay inside the infrastructure adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from domain.errors import ConnectorError

XrayTestKind = Literal["manual", "cucumber"]
XrayCreateWarningReason = Literal["link_not_confirmed", "outline_not_confirmed"]
XrayDetailsKind = Literal["manual", "cucumber", "other"]
XrayScenarioType = Literal["scenario", "scenario_outline"]
IssueLinkDirection = Literal["outward", "inward"]
XrayPatchField = Literal[
    "summary", "test_type", "steps", "gherkin", "scenario_type", "component", "story_link"
]
JIRA_PATCH_FIELDS: frozenset[XrayPatchField] = frozenset({"summary", "component", "story_link"})


@dataclass(frozen=True, slots=True)
class XrayTestStep:
    """One manual step: an action, its optional expected result and test data."""

    action: str
    expected: str = ""
    data: str = ""


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


@dataclass(frozen=True, slots=True)
class IssueLinkRef:
    """One Jira link as seen from the test: ``outward`` means test -> ``issue_key``."""

    type_name: str
    direction: IssueLinkDirection
    issue_key: str


@dataclass(frozen=True, slots=True)
class XrayTestDetails:
    """Current state of one existing Xray test, read before any update (#398).

    ``issue_id`` is kept because Xray Cloud mutations address tests by id.
    ``project_key`` is the Jira project the test belongs to, read from Jira.
    ``editable`` names the :data:`XrayPatchField` values this test accepts;
    ``allowed_components`` is ``None`` when the adapter cannot list them.
    """

    key: str
    issue_id: str
    summary: str
    kind: XrayDetailsKind
    project_key: str = ""
    scenario_type: XrayScenarioType | None = None
    steps: tuple[XrayTestStep, ...] = ()
    gherkin: str = ""
    components: tuple[str, ...] = ()
    links: tuple[IssueLinkRef, ...] = ()
    preconditions: int = 0
    editable: frozenset[str] = frozenset()
    allowed_components: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class XrayTestDetailsResult:
    """Details per key; a requested key in neither field was not returned."""

    found: Mapping[str, XrayTestDetails] = field(default_factory=dict)
    unreadable: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class XrayUpdateCapabilities:
    """What the configured adapter can update, independent of any one test.

    ``jira_fields`` covers summary, components and issue links.
    ``story_link_type`` is ``False`` when the configured link type is unknown.
    """

    jira_fields: bool
    story_link_type: bool


@dataclass(frozen=True, slots=True)
class ManualDefinition:
    steps: tuple[XrayTestStep, ...]


@dataclass(frozen=True, slots=True)
class CucumberDefinition:
    gherkin: str
    outline: bool = False


TestDefinition = ManualDefinition | CucumberDefinition
_KINDS = ("manual", "cucumber")
_SCENARIO_TYPES = ("scenario", "scenario_outline")


@dataclass(frozen=True, slots=True)
class XrayTestPatch:
    """Sparse update of one test: every member left ``None`` stays untouched.

    A ``kind_change`` carries the complete target ``definition``; the adapter
    clears the previous definition. A ``scenario_type_change`` stays Cucumber
    and carries the matching ``CucumberDefinition``.

    Raises:
        ValueError: The members do not form a valid patch.
    """

    key: str
    issue_id: str
    summary: str | None = None
    kind_change: tuple[XrayTestKind, XrayTestKind] | None = None
    definition: TestDefinition | None = None
    scenario_type_change: tuple[XrayScenarioType, XrayScenarioType] | None = None
    add_component: str | None = None
    add_story_link: IssueLinkRef | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.issue_id:
            raise ValueError("patch needs the test key and issue id")
        if not self.changed:
            raise ValueError("patch changes nothing")
        if self.kind_change is not None:
            source, target = self.kind_change
            if source not in _KINDS or target not in _KINDS or source == target:
                raise ValueError("kind change must switch between manual and cucumber")
            if _definition_kind(self.definition) != target:
                raise ValueError("kind change needs the complete target definition")
            if self.scenario_type_change is not None:
                raise ValueError("kind change already sets the scenario type")
        if self.scenario_type_change is not None:
            source_type, target_type = self.scenario_type_change
            if (
                source_type not in _SCENARIO_TYPES
                or target_type not in _SCENARIO_TYPES
                or source_type == target_type
            ):
                raise ValueError("scenario type change must switch scenario types")
            definition = self.definition
            if not isinstance(definition, CucumberDefinition) or definition.outline != (
                target_type == "scenario_outline"
            ):
                raise ValueError("scenario type change needs the matching Gherkin definition")

    @property
    def changed(self) -> tuple[XrayPatchField, ...]:
        names: list[XrayPatchField] = []
        if self.summary is not None:
            names.append("summary")
        if self.kind_change is not None:
            names.append("test_type")
        if self.scenario_type_change is not None:
            names.append("scenario_type")
        if isinstance(self.definition, ManualDefinition):
            names.append("steps")
        elif isinstance(self.definition, CucumberDefinition):
            names.append("gherkin")
        if self.add_component is not None:
            names.append("component")
        if self.add_story_link is not None:
            names.append("story_link")
        return tuple(names)


def _definition_kind(definition: TestDefinition | None) -> XrayTestKind | None:
    if isinstance(definition, ManualDefinition):
        return "manual"
    if isinstance(definition, CucumberDefinition):
        return "cucumber"
    return None


class XrayUpdateRejectedError(ConnectorError):
    """Xray answered and refused the update; nothing was written."""

    def __init__(self) -> None:
        super().__init__("Xray rejected the test update")


class XrayUpdateUncertainError(ConnectorError):
    """The update may have been written; ``partial`` once part of it succeeded."""

    def __init__(self, *, partial: bool) -> None:
        super().__init__("The Xray test update outcome is unknown")
        self.partial = partial


class XrayUpdateNotConfirmedError(ConnectorError):
    """The update was written, but reading the test back did not confirm it."""

    def __init__(self) -> None:
        super().__init__("Xray did not confirm the test update")


class XrayRequiredFieldsError(ConnectorError):
    """The project requires fields the adapter cannot fill; nothing was created.

    ``field_names`` holds the Jira display names of those fields, never values.
    """

    def __init__(self, field_names: tuple[str, ...]) -> None:
        super().__init__("Xray project requires fields that could not be filled")
        self.field_names = field_names
