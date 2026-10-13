"""Seam: ``PreviewTestFileScenariosTool.run`` (#396)."""

from __future__ import annotations

import json

import pytest

from domain.errors import ToolArgumentValidationError, TrustedToolValidationError
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.limits import (
    MAX_TEST_FILE_BYTES,
    MAX_TEST_FILE_PATH_CHARS,
    MAX_TEST_FILE_SCENARIOS,
    MAX_TEST_FILES,
    MAX_TEST_FILES_TOTAL_BYTES,
)
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.preview_test_file_scenarios import (
    TOOL_NAME,
    PreviewTestFileScenariosTool,
)

TAGS = TestFileTagConfig(
    test_marker="XRay", story_marker="Story", manual_tags=("manual", "scaffold")
)
ROBOT = (
    "*** Settings ***\nDefault Tags    ABC-1\n\n*** Test Cases ***\n"
    "Scenario: Robot login\n    [Tags]    XRay ABC-2    manual\n"
    "    Given a user    admin\n"
)
FEATURE = (
    "@ABC-3 @team\nFeature: F\n  Background:\n    Given setup\n\n"
    "  Scenario Outline: Gherkin <x>\n    Given <x>\n      | a |\n      | 1 |\n"
    '    And a doc\n      """json\n      {}\n      """\n'
    "    @fast\n    Examples: E\n      | x |\n      | 2 |\n"
)


def _run(arguments: object) -> dict:
    return json.loads(PreviewTestFileScenariosTool(TAGS).run(arguments))  # type: ignore[arg-type]


def test_preview_returns_the_parsed_files_as_compact_json() -> None:
    tool = PreviewTestFileScenariosTool(TAGS)
    raw = tool.run(
        {
            "files": [
                {"path": "tests/a.robot", "content": ROBOT},
                {"path": "features/b.feature", "content": FEATURE},
            ]
        }
    )

    assert tool.name == TOOL_NAME == "software_delivery.preview_test_file_scenarios"
    assert ", " not in raw
    payload = json.loads(raw)
    assert payload["scenario_count"] == 2
    robot, feature = payload["files"]
    assert robot == {
        "path": "tests/a.robot",
        "format": "robot",
        "story_key": "ABC-1",
        "story_candidates": ["ABC-1"],
        "file_tags": {
            "xray_key": None,
            "story_key": None,
            "candidate_keys": ["ABC-1"],
            "plain": [],
        },
        "background": None,
        "scenarios": [
            {
                "line": 5,
                "keyword": "Scenario",
                "summary": "Robot login",
                "kind": "manual",
                "outline": False,
                "steps": [
                    {
                        "line": 7,
                        "keyword": "Given",
                        "text": "Given a user    admin",
                        "arguments": ["a user", "admin"],
                        "data_table": None,
                        "doc_string": None,
                    }
                ],
                "examples": [],
                "tags": {
                    "inherited": {
                        "xray_key": None,
                        "story_key": None,
                        "candidate_keys": ["ABC-1"],
                        "plain": [],
                    },
                    "local": {
                        "xray_key": "ABC-2",
                        "story_key": None,
                        "candidate_keys": [],
                        "plain": ["manual"],
                    },
                    "effective_plain": ["manual"],
                },
                "story_key": "ABC-1",
                "xray_key": "ABC-2",
            }
        ],
    }
    assert feature["background"] == {
        "line": 3,
        "name": "",
        "steps": [
            {
                "line": 4,
                "keyword": "Given",
                "text": "Given setup",
                "arguments": [],
                "data_table": None,
                "doc_string": None,
            }
        ],
    }
    [outline] = feature["scenarios"]
    table_step, doc_step = outline["steps"]
    assert table_step["data_table"] == {
        "line": 8,
        "rows": [{"line": 8, "cells": ["a"]}, {"line": 9, "cells": ["1"]}],
    }
    assert doc_step["doc_string"] == {
        "line": 11,
        "delimiter": '"""',
        "media_type": "json",
        "lines": ["      {}"],
        "indent": 6,
    }
    assert outline["examples"] == [
        {
            "line": 15,
            "keyword": "Examples",
            "name": "E",
            "tags": ["fast"],
            "header": {"line": 16, "cells": ["x"]},
            "rows": [{"line": 17, "cells": ["2"]}],
        }
    ]
    assert outline["tags"]["effective_plain"] == ["team"]


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        {},
        {"files": [], "extra": 1},
        {"files": "a.robot"},
        {"files": []},
        {"files": ["a.robot"]},
        {"files": [{"path": "a.robot"}]},
        {"files": [{"path": "a.robot", "content": "x", "extra": 1}]},
        {"files": [{"path": 1, "content": "x"}]},
        {"files": [{"path": "  ", "content": "x"}]},
        {"files": [{"path": "a\x00.robot", "content": "x"}]},
        {"files": [{"path": "a" * MAX_TEST_FILE_PATH_CHARS + ".robot", "content": "x"}]},
        {"files": [{"path": "a.robot", "content": 1}]},
        {"files": [{"path": "a.robot", "content": " \n\t "}]},
    ],
)
def test_invalid_arguments_are_untrusted_validation_errors(arguments: object) -> None:
    with pytest.raises(ToolArgumentValidationError) as caught:
        _run(arguments)

    assert not isinstance(caught.value, TrustedToolValidationError)


def _file(path: str, content: str = "*** Test Cases ***\n") -> dict[str, str]:
    return {"path": path, "content": content}


def _reason(arguments: object) -> TestFileValidationError:
    with pytest.raises(TestFileValidationError) as caught:
        _run(arguments)
    return caught.value


def test_too_many_files_is_rejected() -> None:
    error = _reason({"files": [_file(f"t{i}.robot") for i in range(MAX_TEST_FILES + 1)]})

    assert (error.path, error.line, error.reason) == (None, None, Reason.TOO_MANY_FILES)


def test_sizes_and_extensions_are_checked_before_any_file_is_parsed() -> None:
    malformed_first = _file("bad.feature", "not gherkin\n")

    oversized = _reason(
        {"files": [malformed_first, _file("big.robot", "x" * (MAX_TEST_FILE_BYTES + 1))]}
    )
    unsupported = _reason({"files": [malformed_first, _file("notes.txt")]})

    assert (oversized.path, oversized.reason) == ("big.robot", Reason.FILE_TOO_LARGE)
    assert (unsupported.path, unsupported.reason) == ("notes.txt", Reason.UNSUPPORTED_EXTENSION)


def test_multibyte_content_counts_utf8_bytes() -> None:
    content = "é" * (MAX_TEST_FILE_BYTES // 2 + 1)

    assert _reason({"files": [_file("t.robot", content)]}).reason is Reason.FILE_TOO_LARGE


def test_total_size_is_limited() -> None:
    per_file = MAX_TEST_FILE_BYTES
    count = MAX_TEST_FILES_TOTAL_BYTES // per_file + 1
    files = [_file(f"t{i}.robot", "#" * per_file) for i in range(count)]

    assert _reason({"files": files}).reason is Reason.TOTAL_TOO_LARGE


def test_scenario_budget_spans_files_and_names_the_first_scenario_over_it() -> None:
    first_count = MAX_TEST_FILE_SCENARIOS - 1
    first = "*** Test Cases ***\n" + "".join(
        f"Scenario: S{i}\n    Given x\n" for i in range(first_count)
    )
    second = "Feature: F\n  Scenario: A\n    Given x\n  Scenario: B\n    Given y\n"

    error = _reason({"files": [_file("a.robot", first), _file("b.feature", second)]})

    assert (error.path, error.line, error.reason) == ("b.feature", 4, Reason.TOO_MANY_SCENARIOS)


def test_parse_errors_propagate_typed() -> None:
    error = _reason({"files": [_file("bad.feature", "Feature: F\n  Rule: R\n")]})

    assert (error.path, error.line, error.reason) == ("bad.feature", 2, Reason.UNSUPPORTED_RULE)
