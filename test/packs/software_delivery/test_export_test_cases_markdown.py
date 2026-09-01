"""Tests for Software Delivery Markdown test-case export formatter."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.contracts import GeneratedTestCase, TestGenerationResult
from packs.software_delivery.export_test_cases_markdown import (
    export_test_cases_markdown,
    structural_reference_headings,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _steps_result() -> TestGenerationResult:
    return TestGenerationResult(
        "steps",
        (
            GeneratedTestCase(
                "Login with MFA",
                ("Open login page", "Submit credentials"),
                "User is authenticated.",
                (SourceReference("US-12", "user_story"),),
            ),
            GeneratedTestCase(
                "Reset password",
                ("Open reset page", "Submit email"),
                "Reset email sent.",
                (
                    SourceReference("US-12", "user_story"),
                    SourceReference("AC-3", "acceptance_criteria"),
                ),
            ),
        ),
    )


def _assert_fixed_structure(markdown: str, *, cases: int = 1) -> None:
    assert markdown.startswith("# Test Cases\n")
    assert markdown.count("### Steps") == cases
    assert markdown.count("### Expected result") == cases
    assert len(structural_reference_headings(markdown)) == cases


def test_export_matches_golden_fixture_for_steps_style() -> None:
    expected = (_FIXTURES / "sample_export.md").read_text(encoding="utf-8")
    assert export_test_cases_markdown(_steps_result()) == expected


def test_gherkin_style_renders_steps_as_bullets() -> None:
    result = TestGenerationResult(
        "gherkin",
        (
            GeneratedTestCase(
                "Login with MFA",
                (
                    "Given the user is on the login page",
                    "When the user submits valid credentials",
                    "Then the user is authenticated",
                ),
                "User is authenticated.",
                (SourceReference("US-12", "user_story"),),
            ),
        ),
    )
    expected = """\
# Test Cases

**Output style:** gherkin

## 1. `Login with MFA`

### Steps

- `Given the user is on the login page`
- `When the user submits valid credentials`
- `Then the user is authenticated`

### Expected result

```
User is authenticated.
```

### References

- `US-12` (`user_story`)
"""
    assert export_test_cases_markdown(result) == expected


def test_malicious_markdown_is_contained_without_breaking_structure() -> None:
    result = TestGenerationResult(
        "steps",
        (
            GeneratedTestCase(
                "Login\n\n## Injected heading",
                ("Open page\n\n## Injected step",),
                "User is authenticated.\n\n## Injected expected",
                (SourceReference("US-`12", "user_story\n\n## Injected type"),),
            ),
        ),
    )
    markdown = export_test_cases_markdown(result)
    _assert_fixed_structure(markdown)
    assert "## 1. `Login ## Injected heading`" in markdown
    assert "1. `Open page ## Injected step`" in markdown
    assert "## Injected expected" in markdown
    assert "``US-`12``" in markdown
    assert "(`user_story ## Injected type`)" in markdown
    assert markdown.endswith("- ``US-`12`` (`user_story ## Injected type`)\n")


@pytest.mark.parametrize(
    "payload",
    [
        "Before\n```\n### References\n- injected",
        "unclosed ~~~ fence",
        "<!-- hidden -->",
        "<script>alert(1)</script>",
        "```` nested fences ````",
        "~~~\n### References\n~~~",
    ],
)
def test_expected_payloads_cannot_consume_references_heading(payload: str) -> None:
    result = TestGenerationResult(
        "steps",
        (
            GeneratedTestCase(
                "Case",
                ("Act",),
                payload,
                (SourceReference("US-1", "user_story"),),
            ),
        ),
    )
    markdown = export_test_cases_markdown(result)
    _assert_fixed_structure(markdown)
    assert markdown.endswith("- `US-1` (`user_story`)\n")
    assert len(structural_reference_headings(markdown)) == 1


def test_consecutive_backticks_in_source_id_use_adaptive_delimiter() -> None:
    result = TestGenerationResult(
        "steps",
        (
            GeneratedTestCase(
                "Case",
                ("Act",),
                "OK",
                (SourceReference("US-``12", "user_story"),),
            ),
        ),
    )
    markdown = export_test_cases_markdown(result)
    _assert_fixed_structure(markdown)
    assert "```US-``12```" in markdown


def test_source_id_with_leading_or_trailing_backticks_uses_spaced_delimiter() -> None:
    result = TestGenerationResult(
        "steps",
        (
            GeneratedTestCase(
                "Case",
                ("Act",),
                "OK",
                (SourceReference("`US-12`", "user_story"),),
            ),
        ),
    )
    markdown = export_test_cases_markdown(result)
    assert "`` `US-12` ``" in markdown


def test_reference_type_with_consecutive_backticks_uses_adaptive_delimiter() -> None:
    result = TestGenerationResult(
        "steps",
        (
            GeneratedTestCase(
                "Case",
                ("Act",),
                "OK",
                (SourceReference("US-1", "type``name"),),
            ),
        ),
    )
    markdown = export_test_cases_markdown(result)
    _assert_fixed_structure(markdown)
    assert "(```type``name```)" in markdown
