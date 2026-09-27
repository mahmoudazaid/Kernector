"""Composition tests for the #305 test-case export render adapter."""

from types import SimpleNamespace

from application.markdown import MarkdownDocument, MarkdownSection, render_markdown
from composition.software_delivery_export import (
    draft_export_case_arguments,
    render_export_markdown,
)
from packs.software_delivery.tools.export_test_cases_google_drive import (
    ExportCase,
    ExportContent,
)


def test_titles_only_content_matches_shared_renderer_shape() -> None:
    rendered = render_export_markdown(
        ExportContent(
            document_title="Issue 482",
            titles=("Login with MFA", "Checkout fails"),
        )
    )
    expected = render_markdown(
        MarkdownDocument(
            title="Issue 482",
            sections=(
                MarkdownSection(
                    heading="Selected tests",
                    bullet_items=("Login with MFA", "Checkout fails"),
                ),
            ),
        )
    )
    assert rendered == expected


def test_full_cases_render_feature_file_and_manual_lists() -> None:
    rendered = render_export_markdown(
        ExportContent(
            document_title="Issue 482",
            titles=("Checkout fails", "Login with MFA"),
            cases=(
                ExportCase(
                    title="Checkout fails",
                    test_type="cucumber",
                    gherkin="Scenario: Checkout fails\n  Given an empty cart",
                ),
                ExportCase(
                    title="Login with MFA",
                    test_type="manual",
                    preconditions=("Logged out",),
                    steps=("Open login", "Enter code"),
                    expected_result=("Home loads",),
                ),
            ),
            cucumber_feature="Checkout",
            cucumber_background="Given the store is open",
        )
    )
    assert rendered == (
        "# Issue 482\n\n"
        "## Cucumber\n\n"
        "```gherkin\n"
        "Feature: Checkout\n"
        "\n"
        "  Background:\n"
        "    Given the store is open\n"
        "\n"
        "  Scenario: Checkout fails\n"
        "    Given an empty cart\n"
        "```\n\n"
        "## Manual\n\n"
        "### Login with MFA\n\n"
        "#### Preconditions\n\n"
        "1. Logged out\n\n"
        "#### Steps\n\n"
        "1. Open login\n"
        "2. Enter code\n\n"
        "#### Expected result\n\n"
        "1. Home loads\n"
    )


def test_feature_file_names_scenarios_from_titles_and_aligns_steps() -> None:
    rendered = render_export_markdown(
        ExportContent(
            document_title="Issue 482",
            titles=("Personality options", "Each personality"),
            cases=(
                ExportCase(
                    title="Personality options",
                    test_type="cucumber",
                    gherkin="Given the agent UI is open\nWhen I open the picker\nThen I see options",
                ),
                ExportCase(
                    title="Each personality",
                    test_type="cucumber",
                    gherkin=(
                        "Given I pick <style>\nThen replies are <style>\n"
                        "Examples:\n| style |\n| formal |"
                    ),
                ),
            ),
            cucumber_feature="Personality",
            cucumber_background="",
        )
    )
    assert (
        "Feature: Personality\n"
        "\n"
        "  Scenario: Personality options\n"
        "    Given the agent UI is open\n"
        "    When I open the picker\n"
        "    Then I see options\n"
        "\n"
        "  Scenario Outline: Each personality\n"
        "    Given I pick <style>\n"
        "    Then replies are <style>\n"
        "    Examples:\n"
        "      | style |\n"
        "      | formal |\n"
    ) in rendered


def _case(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "candidate_id": "c1",
        "test_type": "manual",
        "availability": "available",
        "preconditions": "Logged out",
        "steps": ("Open login", " "),
        "expected_result": "Home loads\nBanner shown",
        "gherkin": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_draft_case_arguments_skip_unselected_and_unavailable() -> None:
    draft = SimpleNamespace(
        candidates=(
            SimpleNamespace(candidate_id="c1", title="Login", selected=True),
            SimpleNamespace(candidate_id="c2", title="Scenario", selected=True),
            SimpleNamespace(candidate_id="c3", title="Unselected", selected=False),
            SimpleNamespace(candidate_id="c4", title="Unclear", selected=True),
        ),
        generated_cases=(
            _case(),
            _case(
                candidate_id="c2",
                test_type="cucumber",
                preconditions="",
                steps=(),
                expected_result="",
                gherkin="Scenario: X\n  Given y",
            ),
            _case(candidate_id="c3"),
            _case(
                candidate_id="c4",
                availability="insufficient_evidence",
                preconditions="",
                steps=(),
                expected_result="",
            ),
        ),
        cucumber_feature="Feature title",
        cucumber_background="",
    )
    assert draft_export_case_arguments(draft) == {
        "cases": [
            {
                "title": "Login",
                "test_type": "manual",
                "preconditions": ["Logged out"],
                "steps": ["Open login"],
                "expected_result": ["Home loads", "Banner shown"],
            },
            {
                "title": "Scenario",
                "test_type": "cucumber",
                "gherkin": "Scenario: X\n  Given y",
            },
        ],
        "cucumber_feature": "Feature title",
        "cucumber_background": "",
    }


def test_draft_without_generated_cases_adds_no_arguments() -> None:
    draft = SimpleNamespace(
        candidates=(SimpleNamespace(candidate_id="c1", title="Login", selected=True),),
        generated_cases=(),
    )
    assert draft_export_case_arguments(draft) == {}
