"""Composition tests for titles-only #305 export render adapter."""

from application.markdown import render_markdown, MarkdownDocument, MarkdownSection
from composition.software_delivery_export import render_export_markdown


def test_render_export_markdown_uses_shared_renderer_shape() -> None:
    rendered = render_export_markdown(
        "Issue 482",
        ["Login with MFA", "Checkout fails"],
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
