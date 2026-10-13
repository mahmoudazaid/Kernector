"""Xray Server/Data Center test details and sparse update bodies (#398).

One ``GET /issue/{key}?expand=schema,editmeta`` gives the current values and
what Jira lets the caller edit. Xray fields are found by their custom field
type key in ``schema`` (values) and ``editmeta`` (operations and option ids).
Create metadata is never treated as proof that a field is editable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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

TEST_TYPE_FIELD = "com.xpandit.plugins.xray:test-type-custom-field"
MANUAL_STEPS_FIELD = "com.xpandit.plugins.xray:manual-test-steps-custom-field"
CUCUMBER_TYPE_FIELD = "com.xpandit.plugins.xray:automated-test-type-custom-field"
SCENARIO_FIELD = "com.xpandit.plugins.xray:steps-editor-custom-field"
PRECONDITIONS_FIELD = "com.xpandit.plugins.xray:test-precondition-custom-field"

DETAILS_PARAMS = {"expand": "schema,editmeta"}

_SCENARIO_TYPES: dict[str, XrayScenarioType] = {
    "scenario": "scenario",
    "scenario outline": "scenario_outline",
}


@dataclass(frozen=True, slots=True)
class EditTarget:
    """Editable Xray field ids and option ids of one test, from its editmeta."""

    test_type_field: str | None = None
    manual_option: str | None = None
    cucumber_option: str | None = None
    steps_field: str | None = None
    cucumber_type_field: str | None = None
    scenario_option: str | None = None
    outline_option: str | None = None
    scenario_field: str | None = None
    summary: bool = False
    components: bool = False
    issuelinks: bool = False

    @property
    def editable(self) -> frozenset[str]:
        names: set[str] = set()
        if self.summary:
            names.add("summary")
        if self.steps_field:
            names.add("steps")
        if self.scenario_field:
            names.add("gherkin")
        outline_ready = None not in (
            self.cucumber_type_field,
            self.scenario_option,
            self.outline_option,
        )
        if outline_ready and self.scenario_field:
            names.add("scenario_type")
        if (
            outline_ready
            and None not in (self.test_type_field, self.manual_option, self.cucumber_option)
            and {"steps", "gherkin"} <= names
        ):
            names.add("test_type")
        if self.components:
            names.add("component")
        if self.issuelinks:
            names.add("story_link")
        return frozenset(names)


def parse_issue(key: str, payload: object) -> tuple[XrayTestDetails, EditTarget]:
    """Details and edit target of one test.

    Raises:
        Unreadable: The answer is malformed or the test kind cannot be read.
    """
    if not isinstance(payload, Mapping):
        raise Unreadable(key)
    fields = mapping(payload.get("fields"))
    issue_id = payload.get("id")
    summary = fields.get("summary")
    if payload.get("key") != key or not is_text(issue_id) or not isinstance(summary, str):
        raise Unreadable(key)
    ids = _custom_ids(mapping(payload.get("schema")))
    if TEST_TYPE_FIELD not in ids:
        raise Unreadable(key)
    kind = _kind(fields.get(ids[TEST_TYPE_FIELD]))
    scenario_type = _scenario_type(fields.get(ids.get(CUCUMBER_TYPE_FIELD, "")), kind)
    edit = mapping(mapping(payload.get("editmeta")).get("fields"))
    details = XrayTestDetails(
        key=key,
        issue_id=str(issue_id),
        summary=summary,
        kind=kind,
        scenario_type=scenario_type,
        steps=_steps(fields.get(ids.get(MANUAL_STEPS_FIELD, ""))),
        gherkin=optional_text(fields.get(ids.get(SCENARIO_FIELD, ""))),
        components=parse_names(fields.get("components")),
        links=parse_links(fields.get("issuelinks")),
        preconditions=_count(fields.get(ids.get(PRECONDITIONS_FIELD, ""))),
        editable=(target := _target(edit)).editable,
        allowed_components=_allowed_components(edit.get("components")),
    )
    return details, target


def update_body(patch: XrayTestPatch, target: EditTarget) -> dict[str, object] | None:
    """``PUT /issue/{key}`` body with only the patch members, or ``None`` if not editable.

    A kind switch writes the complete target definition and clears the old
    one, because Xray DC may keep it depending on a global preference.
    """
    if not set(patch.changed) <= target.editable:
        return None
    fields: dict[str, object] = {}
    if patch.summary is not None:
        fields["summary"] = patch.summary
    definition = patch.definition
    if patch.kind_change is not None:
        option = target.manual_option if patch.kind_change[1] == "manual" else target.cucumber_option
        fields[str(target.test_type_field)] = {"id": option}
    if isinstance(definition, CucumberDefinition):
        if patch.kind_change is not None or patch.scenario_type_change is not None:
            option = target.outline_option if definition.outline else target.scenario_option
            fields[str(target.cucumber_type_field)] = {"id": option}
        fields[str(target.scenario_field)] = definition.gherkin
        if patch.kind_change is not None:
            fields[str(target.steps_field)] = {"steps": []}
    elif isinstance(definition, ManualDefinition):
        fields[str(target.steps_field)] = steps_value(definition.steps)
        if patch.kind_change is not None:
            fields[str(target.scenario_field)] = ""
    update: dict[str, object] = {}
    if patch.add_component is not None:
        update["components"] = [{"add": {"name": patch.add_component}}]
    if patch.add_story_link is not None:
        link = patch.add_story_link
        update["issuelinks"] = [
            {"add": {"type": {"name": link.type_name}, "outwardIssue": {"key": link.issue_key}}}
        ]
    body: dict[str, object] = {}
    if fields:
        body["fields"] = fields
    if update:
        body["update"] = update
    return body


def steps_value(steps: tuple[XrayTestStep, ...]) -> dict[str, object]:
    """Xray DC manual steps field value."""
    return {
        "steps": [
            {
                "index": index,
                "fields": {
                    "action": step.action,
                    "data": step.data,
                    "expected result": step.expected,
                },
            }
            for index, step in enumerate(steps, start=1)
        ]
    }


def _target(edit: Mapping[str, object]) -> EditTarget:
    by_custom: dict[str, tuple[str, Mapping[str, object]]] = {}
    for field_id, meta in edit.items():
        custom = mapping(mapping(meta).get("schema")).get("custom")
        if isinstance(custom, str) and _can(meta, "set"):
            by_custom.setdefault(custom, (field_id, mapping(meta)))
    test_type = by_custom.get(TEST_TYPE_FIELD)
    cucumber_type = by_custom.get(CUCUMBER_TYPE_FIELD)
    return EditTarget(
        test_type_field=test_type[0] if test_type else None,
        manual_option=_option(test_type, "manual"),
        cucumber_option=_option(test_type, "cucumber"),
        steps_field=_field_id(by_custom.get(MANUAL_STEPS_FIELD)),
        cucumber_type_field=cucumber_type[0] if cucumber_type else None,
        scenario_option=_option(cucumber_type, "scenario"),
        outline_option=_option(cucumber_type, "scenario outline"),
        scenario_field=_field_id(by_custom.get(SCENARIO_FIELD)),
        summary=_can(edit.get("summary"), "set"),
        components=_can(edit.get("components"), "add"),
        issuelinks=_can(edit.get("issuelinks"), "add"),
    )


def _custom_ids(schema: Mapping[str, object]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for field_id, meta in schema.items():
        custom = mapping(meta).get("custom")
        if isinstance(custom, str):
            ids.setdefault(custom, field_id)
    return ids


def _kind(value: object) -> XrayDetailsKind:
    if not isinstance(value, Mapping) or not is_text(value.get("value")):
        raise Unreadable("test type")
    name = str(value["value"]).strip().casefold()
    if name == "manual":
        return "manual"
    if name == "cucumber":
        return "cucumber"
    return "other"


def _scenario_type(value: object, kind: XrayDetailsKind) -> XrayScenarioType | None:
    if value is None:
        return None
    label = mapping(value).get("value")
    scenario_type = _SCENARIO_TYPES.get(str(label).strip().casefold()) if is_text(label) else None
    if scenario_type is None and kind == "cucumber":
        raise Unreadable("scenario type")
    return scenario_type


def _steps(value: object) -> tuple[XrayTestStep, ...]:
    if value is None:
        return ()
    rows = mapping(value).get("steps")
    if not isinstance(rows, list):
        raise Unreadable("steps")
    steps: list[XrayTestStep] = []
    for row in rows:
        cells = row.get("fields") if isinstance(row, Mapping) else None
        if not isinstance(cells, Mapping):
            raise Unreadable("steps")
        by_name = {str(name).strip().casefold(): cell for name, cell in cells.items()}
        steps.append(
            XrayTestStep(
                action=optional_text(by_name.get("action")),
                expected=optional_text(by_name.get("expected result")),
                data=optional_text(by_name.get("data")),
            )
        )
    return tuple(steps)


def _allowed_components(meta: object) -> frozenset[str] | None:
    options = mapping(meta).get("allowedValues")
    if not isinstance(options, list):
        return None
    return frozenset(
        str(name) for option in options if is_text(name := mapping(option).get("name"))
    )


def _count(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, list):
        raise Unreadable("preconditions")
    return len(value)


def _option(field: tuple[str, Mapping[str, object]] | None, label: str) -> str | None:
    options = field[1].get("allowedValues") if field else None
    if not isinstance(options, list):
        return None
    for option in options:
        option_map = mapping(option)
        value = option_map.get("value")
        if is_text(value) and str(value).strip().casefold() == label and is_text(option_map.get("id")):
            return str(option_map["id"])
    return None


def _field_id(field: tuple[str, Mapping[str, object]] | None) -> str | None:
    return field[0] if field else None


def _can(meta: object, operation: str) -> bool:
    operations = mapping(meta).get("operations")
    return isinstance(operations, list) and operation in operations
