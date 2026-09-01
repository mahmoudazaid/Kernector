"""Tests for Software Delivery Markdown test-case export formatter."""

from __future__ import annotations

from pathlib import Path

from domain.knowledge import SourceReference
from packs.software_delivery.contracts import GeneratedTestCase, TestGenerationResult
from packs.software_delivery.export_test_cases_markdown import export_test_cases_markdown

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

## 1. Login with MFA

### Steps

- Given the user is on the login page
- When the user submits valid credentials
- Then the user is authenticated

### Expected result

User is authenticated.

### References

- `US-12` (user_story)
"""
    assert export_test_cases_markdown(result) == expected


def test_malicious_markdown_is_normalized_without_breaking_structure() -> None:
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
    assert markdown.count("## 1.") == 1
    assert markdown.count("### Steps") == 1
    assert markdown.count("### Expected result") == 1
    assert markdown.count("### References") == 1
    assert "## 1. Login \\#\\# Injected heading" in markdown
    assert "1. Open page \\#\\# Injected step" in markdown
    assert "\\## Injected expected" in markdown
    assert "``US-`12``" in markdown
    assert "(user_story \\#\\# Injected type)" in markdown
