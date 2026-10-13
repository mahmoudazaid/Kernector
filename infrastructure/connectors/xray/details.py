"""Parsing and read-back checks shared by the Xray Server and Cloud updaters (#398).

Both deployments return Jira ``components`` and ``issuelinks`` in the Jira REST
shape, and both confirm a definition change by reading the test back.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.test_management.xray import (
    CucumberDefinition,
    IssueLinkRef,
    ManualDefinition,
    XrayTestDetails,
    XrayTestPatch,
)


class Unreadable(ValueError):
    """The answer for one test does not have the expected shape."""


def parse_links(value: object) -> tuple[IssueLinkRef, ...]:
    """Jira ``issuelinks`` seen from the test; ``outward`` means test -> other issue."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise Unreadable("links")
    links: list[IssueLinkRef] = []
    for link in value:
        link_map = mapping(link)
        name = mapping(link_map.get("type")).get("name")
        outward = mapping(link_map.get("outwardIssue")).get("key")
        inward = mapping(link_map.get("inwardIssue")).get("key")
        if not is_text(name) or is_text(outward) == is_text(inward):
            raise Unreadable("links")
        if is_text(outward):
            links.append(IssueLinkRef(str(name), "outward", str(outward)))
        else:
            links.append(IssueLinkRef(str(name), "inward", str(inward)))
    return tuple(links)


def parse_names(value: object) -> tuple[str, ...]:
    """Names of Jira ``components``."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise Unreadable("components")
    names = tuple(mapping(item).get("name") for item in value)
    if not all(is_text(name) for name in names):
        raise Unreadable("components")
    return tuple(str(name) for name in names)


def parse_project_key(value: object) -> str:
    """Key of the Jira ``project`` field."""
    key = mapping(value).get("key")
    if not isinstance(key, str) or not key:
        raise Unreadable("project")
    return key


def confirms_definition(patch: XrayTestPatch, details: XrayTestDetails) -> bool:
    """The read-back shows the patch's kind and definition and no other definition."""
    definition = patch.definition
    if isinstance(definition, CucumberDefinition):
        expected_type = "scenario_outline" if definition.outline else "scenario"
        return (
            details.kind == "cucumber"
            and (details.scenario_type or "scenario") == expected_type
            and _same_text(details.gherkin, definition.gherkin)
            and not details.steps
        )
    if isinstance(definition, ManualDefinition):
        return (
            details.kind == "manual"
            and details.steps == definition.steps
            and not details.gherkin.strip()
        )
    return False


def mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def is_text(value: object) -> bool:
    return isinstance(value, str | int) and not isinstance(value, bool) and str(value) != ""


def optional_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Unreadable("text")
    return value


def _same_text(left: str, right: str) -> bool:
    return left.replace("\r\n", "\n").strip() == right.replace("\r\n", "\n").strip()
