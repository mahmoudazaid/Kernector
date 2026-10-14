"""Seam: ``WriteXrayKeysToFilesTool.run`` (#399)."""

from __future__ import annotations

import json

import pytest

from domain.errors import TrustedToolValidationError
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import (
    TestFileValidationError,
    XrayKeyWritebackValidationError,
)
from packs.software_delivery.limits import MAX_TEST_FILE_SCENARIOS
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools import write_xray_keys_to_files as tool_module
from packs.software_delivery.tools.write_xray_keys_to_files import WriteXrayKeysToFilesTool

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))
ROBOT_PATH = "tests/login.robot"
FEATURE_PATH = "features/login.feature"


def _text(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _run(files: dict[str, str], keys: dict[str, str]) -> dict:
    tool = WriteXrayKeysToFilesTool(TAGS)
    arguments = {
        "files": [{"path": path, "content": content} for path, content in files.items()],
        "keys": keys,
    }
    return json.loads(tool.run(arguments))


def _rejected(files: dict[str, str], keys: dict[str, str]) -> TestFileValidationError:
    with pytest.raises(TestFileValidationError) as caught:
        _run(files, keys)
    return caught.value


ROBOT = _text(
    "*** Test Cases ***",
    "Scenario: A",
    "    [Tags]    XRay ABC-1",
    "    Given a",
    "Scenario: B",
    "    Given b",
)


def test_a_key_released_by_another_scenario_in_the_same_call_can_be_reassigned() -> None:
    payload = _run(
        {ROBOT_PATH: ROBOT},
        {f"{ROBOT_PATH}::A": "ABC-2", f"{ROBOT_PATH}::B": "ABC-1"},
    )

    assert [(r["summary"], r["previous_key"], r["status"]) for r in payload["results"]] == [
        ("A", "ABC-1", "REPLACED"),
        ("B", None, "TAGGED"),
    ]


def test_two_scenarios_ending_with_the_same_key_are_rejected_at_the_second() -> None:
    error = _rejected({ROBOT_PATH: ROBOT}, {f"{ROBOT_PATH}::B": "ABC-1"})

    assert (error.path, error.line, error.reason) == (ROBOT_PATH, 5, Reason.DUPLICATE_KEY_OWNER)


def test_the_same_key_mapped_twice_is_rejected() -> None:
    error = _rejected(
        {ROBOT_PATH: ROBOT}, {f"{ROBOT_PATH}::A": "ABC-5", f"{ROBOT_PATH}::B": "ABC-5"}
    )

    assert (error.line, error.reason) == (5, Reason.DUPLICATE_KEY_OWNER)


def test_existing_duplicate_owners_are_rejected_even_when_unmapped() -> None:
    feature = _text("Feature: F", "  @XRay:ABC-1", "  Scenario: C", "    Given c")

    error = _rejected(
        {ROBOT_PATH: ROBOT, FEATURE_PATH: feature}, {f"{ROBOT_PATH}::B": "ABC-7"}
    )

    assert (error.path, error.line, error.reason) == (
        FEATURE_PATH,
        3,
        Reason.DUPLICATE_KEY_OWNER,
    )


@pytest.mark.parametrize(
    "feature",
    [
        _text("@Story:ABC-7", "Feature: F", "  Scenario: S", "    Given s"),
        _text("Feature: F [ABC-7]", "  Scenario: S", "    Given s"),
        _text("Feature: F", "  @Story:ABC-7", "  Scenario: S", "    Given s"),
        _text(
            "Feature: F",
            "  Scenario: S",
            "    Given s",
            "  @ABC-7",
            "  Scenario: Other",
            "    Given o",
        ),
    ],
    ids=["file-story", "title-story", "own-story", "other-bare-key"],
)
def test_a_key_already_used_as_a_story_or_other_key_tag_is_rejected(feature: str) -> None:
    error = _rejected({FEATURE_PATH: feature}, {f"{FEATURE_PATH}::S": "ABC-7"})

    assert (error.path, error.reason) == (FEATURE_PATH, Reason.KEY_USED_AS_OTHER_TAG)


def test_a_robot_default_tags_key_is_a_file_level_key() -> None:
    robot = _text(
        "*** Settings ***", "Default Tags    ABC-7", "*** Test Cases ***", "Scenario: S", "  Given s"
    )

    error = _rejected({ROBOT_PATH: robot}, {f"{ROBOT_PATH}::S": "ABC-7"})

    assert (error.line, error.reason) == (4, Reason.KEY_USED_AS_OTHER_TAG)


def test_a_bare_copy_on_the_same_scenario_is_its_own_identity() -> None:
    robot = _text("*** Test Cases ***", "Scenario: S", "    [Tags]    ABC-7", "    Given s")

    payload = _run({ROBOT_PATH: robot}, {f"{ROBOT_PATH}::S": "ABC-7"})

    assert payload["files"][0]["content"] == _text(
        "*** Test Cases ***", "Scenario: S", "    [Tags]    XRay ABC-7", "    Given s"
    )


@pytest.mark.parametrize(
    ("identity", "path", "reason"),
    [
        ("tests/other.robot::A", None, Reason.UNKNOWN_FILE),
        (f"{ROBOT_PATH}::Missing", ROBOT_PATH, Reason.UNKNOWN_SCENARIO),
    ],
)
def test_unknown_files_and_scenarios_are_rejected(
    identity: str, path: str | None, reason: Reason
) -> None:
    error = _rejected({ROBOT_PATH: ROBOT}, {identity: "ABC-9"})

    assert (error.path, error.line, error.reason) == (path, None, reason)


def test_a_key_that_is_not_an_issue_key_is_rejected_at_the_scenario() -> None:
    error = _rejected({ROBOT_PATH: ROBOT}, {f"{ROBOT_PATH}::B": "abc-1"})

    assert (error.path, error.line, error.reason) == (ROBOT_PATH, 5, Reason.INVALID_XRAY_KEY)


STATUS_ROBOT = _text(
    "*** Test Cases ***",
    "Scenario: New",
    "    Given a",
    "Scenario: Moved",
    "    [Tags]    XRay ABC-2",
    "    Given b",
    "Scenario: Messy",
    "    [Tags]    xray:ABC-3    XRay ABC-3",
    "    Given c",
    "Scenario: Clean",
    "    [Tags]    XRay ABC-4",
    "    Given d",
    "Scenario: Unmapped",
    "    [Tags]    XRay ABC-5    smoke",
    "    Given e",
)


def test_run_returns_full_content_diffs_and_one_result_per_mapping() -> None:
    untouched = _text("Feature: F", "  Scenario: Other", "    Given x")
    tool = WriteXrayKeysToFilesTool(TAGS)

    raw = tool.run(
        {
            "files": [
                {"path": ROBOT_PATH, "content": STATUS_ROBOT},
                {"path": FEATURE_PATH, "content": untouched},
            ],
            "keys": {
                f"{ROBOT_PATH}::New": "ABC-1",
                f"{ROBOT_PATH}::Moved": "ABC-9",
                f"{ROBOT_PATH}::Messy": "ABC-3",
                f"{ROBOT_PATH}::Clean": "ABC-4",
            },
        }
    )

    assert tool.name == "software_delivery.write_xray_keys_to_files"
    assert ", " not in raw
    payload = json.loads(raw)
    robot, feature = payload["files"]
    assert robot["path"] == ROBOT_PATH and robot["changed"] is True
    assert robot["content"] == _text(
        "*** Test Cases ***",
        "Scenario: New",
        "    [Tags]    XRay ABC-1",
        "    Given a",
        "Scenario: Moved",
        "    [Tags]    XRay ABC-9",
        "    Given b",
        "Scenario: Messy",
        "    [Tags]    XRay ABC-3",
        "    Given c",
        "Scenario: Clean",
        "    [Tags]    XRay ABC-4",
        "    Given d",
        "Scenario: Unmapped",
        "    [Tags]    XRay ABC-5    smoke",
        "    Given e",
    )
    assert robot["diff"].startswith(f"--- a/{ROBOT_PATH}\n+++ b/{ROBOT_PATH}\n@@ ")
    assert "+    [Tags]    XRay ABC-9\n" in robot["diff"]
    assert feature == {"path": FEATURE_PATH, "changed": False, "content": untouched, "diff": ""}
    assert payload["results"] == [
        {
            "path": ROBOT_PATH,
            "line": line,
            "summary": summary,
            "key": key,
            "previous_key": previous,
            "status": status,
        }
        for line, summary, key, previous, status in [
            (2, "New", "ABC-1", None, "TAGGED"),
            (4, "Moved", "ABC-9", "ABC-2", "REPLACED"),
            (7, "Messy", "ABC-3", "ABC-3", "NORMALIZED"),
            (10, "Clean", "ABC-4", "ABC-4", "UNCHANGED"),
        ]
    ]
    assert payload["counts"] == {"TAGGED": 1, "REPLACED": 1, "NORMALIZED": 1, "UNCHANGED": 1}


@pytest.mark.parametrize(
    "keys",
    [None, [], {}, {"": "ABC-1"}, {f"{ROBOT_PATH}::B": 7}, "ROBOT::B=ABC-1"],
    ids=["none", "list", "empty", "blank-identity", "non-string-key", "string"],
)
def test_malformed_keys_are_rejected_with_a_generic_argument_error(keys: object) -> None:
    tool = WriteXrayKeysToFilesTool(TAGS)

    with pytest.raises(XrayKeyWritebackValidationError):
        tool.run({"files": [{"path": ROBOT_PATH, "content": ROBOT}], "keys": keys})


def test_too_many_keys_and_unknown_arguments_are_rejected() -> None:
    tool = WriteXrayKeysToFilesTool(TAGS)
    files = [{"path": ROBOT_PATH, "content": ROBOT}]
    keys = {f"{ROBOT_PATH}::S{i}": "ABC-1" for i in range(MAX_TEST_FILE_SCENARIOS + 1)}

    with pytest.raises(XrayKeyWritebackValidationError):
        tool.run({"files": files, "keys": keys})
    with pytest.raises(XrayKeyWritebackValidationError):
        tool.run({"files": files, "keys": {f"{ROBOT_PATH}::B": "ABC-9"}, "dry_run": True})


def test_a_result_over_the_size_cap_is_rejected_without_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tool_module, "MAX_XRAY_KEY_WRITEBACK_RESULT_BYTES", 200)

    error = _rejected({ROBOT_PATH: ROBOT}, {f"{ROBOT_PATH}::B": "ABC-9"})

    assert (error.path, error.line, error.reason) == (None, None, Reason.RESULT_TOO_LARGE)
    assert isinstance(error, TrustedToolValidationError)
