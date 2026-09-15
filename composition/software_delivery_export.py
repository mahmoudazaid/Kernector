"""Composition adapters for Software Delivery Markdown export rendering."""

from __future__ import annotations

from collections.abc import Sequence

from application.markdown import MarkdownDocument, MarkdownSection, render_markdown


def render_export_markdown(document_title: str, titles: Sequence[str]) -> str:
    """Map titles-only export input onto the shared #305 Markdown renderer."""
    return render_markdown(
        MarkdownDocument(
            title=document_title,
            sections=(
                MarkdownSection(
                    heading="Selected tests",
                    bullet_items=tuple(titles),
                ),
            ),
        )
    )
