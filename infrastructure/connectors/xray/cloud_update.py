"""Xray Cloud test details and update mutation sequences (#398).

Xray Cloud GraphQL has no Jira-field or issue-link mutation, so with Xray-only
credentials only the test definition can change. Mutations address tests by
``issueId``. A type change clears the old definition with the old kind's own
API first, because Xray drops or keeps it depending on the kind.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from domain.errors import ConnectorError
from domain.test_management.xray import (
    CucumberDefinition,
    ManualDefinition,
    XrayDetailsKind,
    XrayScenarioType,
    XrayTestDetails,
    XrayTestPatch,
    XrayTestStep,
)
from infrastructure.connectors.xray.details import (
    Unreadable,
    is_text,
    mapping,
    optional_text,
    parse_links,
    parse_names,
)
from infrastructure.connectors.xray.errors import MSG_REQUEST_FAILED

DETAILS_SELECTION = (
    "{ total start limit results { issueId testType { id name kind } "
    "steps { id action data result } gherkin scenarioType "
    "preconditions(limit: 1) { total } "
    'jira(fields: ["key", "summary", "components", "issuelinks"]) } }'
)
_REMOVE_ALL_STEPS = "mutation($issueId: String!) { removeAllTestSteps(issueId: $issueId) }"
_ADD_STEP = (
    "mutation($issueId: String!, $step: CreateStepInput!) { "
    "addTestStep(issueId: $issueId, step: $step) { id } }"
)
_UPDATE_TYPE = (
    "mutation($issueId: String!, $testType: UpdateTestTypeInput!) { "
    "updateTestType(issueId: $issueId, testType: $testType) { issueId testType { id kind } } }"
)
_UPDATE_GHERKIN = (
    "mutation($issueId: String!, $gherkin: String!) { "
    "updateGherkinTestDefinition(issueId: $issueId, gherkin: $gherkin) { issueId } }"
)
_SCENARIO_TYPES: dict[str, XrayScenarioType] = {
    "scenario": "scenario",
    "scenario_outline": "scenario_outline",
    "scenario outline": "scenario_outline",
}
DEFINITION_FIELDS = frozenset({"steps", "gherkin", "scenario_type"})


@dataclass(frozen=True, slots=True)
class Mutation:
    """One GraphQL mutation and how to recognise its successful result."""

    name: str
    query: str
    variables: Mapping[str, object] = field(default_factory=dict)
    type_id: str | None = None

    def succeeded(self, result: object, issue_id: str) -> bool:
        if self.name == "removeAllTestSteps":
            return result is not None
        if self.name == "addTestStep":
            return is_text(mapping(result).get("id"))
        if mapping(result).get("issueId") != issue_id:
            return False
        returned = mapping(mapping(result).get("testType")).get("id")
        return self.type_id is None or returned is None or returned == self.type_id


def kind_of(value: object) -> XrayDetailsKind:
    """Casefolded Xray Cloud test type kind: ``Steps`` is manual, ``Gherkin`` cucumber."""
    kind = str(value).strip().casefold() if is_text(value) else ""
    if kind == "steps":
        return "manual"
    if kind == "gherkin":
        return "cucumber"
    return "other"


def parse_test(item: object, *, type_switch: bool) -> tuple[str, XrayTestDetails | None]:
    """Key and details of one ``getTests`` row; ``None`` details when malformed.

    Raises:
        ConnectorError: The row has no readable key or issue id.
    """
    row = mapping(item)
    jira = mapping(row.get("jira"))
    key, issue_id = jira.get("key"), row.get("issueId")
    if not isinstance(key, str) or not key or not is_text(issue_id):
        raise ConnectorError(MSG_REQUEST_FAILED)
    try:
        details = _details(key, str(issue_id), row, jira, type_switch=type_switch)
    except Unreadable:
        return key, None
    return key, details


def mutations(
    patch: XrayTestPatch, *, manual_id: str | None, cucumber_id: str | None
) -> list[Mutation] | None:
    """The verified mutation order for ``patch``; ``None`` when it cannot be sent."""
    issue = {"issueId": patch.issue_id}
    definition = patch.definition
    if patch.kind_change is not None:
        if isinstance(definition, CucumberDefinition) and cucumber_id:
            return [
                Mutation("removeAllTestSteps", _REMOVE_ALL_STEPS, issue),
                _type_change(issue, cucumber_id),
                _gherkin(issue, definition.gherkin),
            ]
        if isinstance(definition, ManualDefinition) and manual_id:
            return [
                _gherkin(issue, ""),
                _type_change(issue, manual_id),
                *_add_steps(issue, definition.steps),
            ]
        return None
    if isinstance(definition, CucumberDefinition):
        return [_gherkin(issue, definition.gherkin)]
    if isinstance(definition, ManualDefinition):
        return [
            Mutation("removeAllTestSteps", _REMOVE_ALL_STEPS, issue),
            *_add_steps(issue, definition.steps),
        ]
    return None


def _details(
    key: str,
    issue_id: str,
    row: Mapping[str, object],
    jira: Mapping[str, object],
    *,
    type_switch: bool,
) -> XrayTestDetails:
    summary = jira.get("summary")
    if not isinstance(summary, str):
        raise Unreadable(key)
    gherkin = optional_text(row.get("gherkin"))
    raw_type = row.get("scenarioType")
    scenario_type = (
        _SCENARIO_TYPES.get(str(raw_type).strip().casefold()) if is_text(raw_type) else None
    )
    if gherkin.strip() and scenario_type is None:
        raise Unreadable(key)
    preconditions = mapping(row.get("preconditions")).get("total", 0)
    if not isinstance(preconditions, int) or isinstance(preconditions, bool):
        raise Unreadable(key)
    editable = DEFINITION_FIELDS | ({"test_type"} if type_switch else set())
    return XrayTestDetails(
        key=key,
        issue_id=issue_id,
        summary=summary,
        kind=kind_of(mapping(row.get("testType")).get("kind")),
        scenario_type=scenario_type,
        steps=_steps(row.get("steps")),
        gherkin=gherkin,
        components=parse_names(jira.get("components")),
        links=parse_links(jira.get("issuelinks")),
        preconditions=preconditions,
        editable=frozenset(editable),
    )


def _steps(value: object) -> tuple[XrayTestStep, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise Unreadable("steps")
    steps: list[XrayTestStep] = []
    for step in value:
        if not isinstance(step, Mapping):
            raise Unreadable("steps")
        steps.append(
            XrayTestStep(
                action=optional_text(step.get("action")),
                expected=optional_text(step.get("result")),
                data=optional_text(step.get("data")),
            )
        )
    return tuple(steps)


def _type_change(issue: Mapping[str, object], type_id: str) -> Mutation:
    return Mutation(
        "updateTestType", _UPDATE_TYPE, {**issue, "testType": {"id": type_id}}, type_id=type_id
    )


def _gherkin(issue: Mapping[str, object], gherkin: str) -> Mutation:
    return Mutation("updateGherkinTestDefinition", _UPDATE_GHERKIN, {**issue, "gherkin": gherkin})


def _add_steps(issue: Mapping[str, object], steps: Sequence[XrayTestStep]) -> list[Mutation]:
    return [
        Mutation(
            "addTestStep",
            _ADD_STEP,
            {**issue, "step": {"action": step.action, "data": step.data, "result": step.expected}},
        )
        for step in steps
    ]
