"""Normalize LangChain chat message content across providers (#462)."""

from __future__ import annotations

from collections.abc import Mapping


def normalize_message_content(content: object) -> str:
    """Flatten string or content-block list payloads into a single string.

    Gemini 3+ and Anthropic may return ``AIMessage.content`` as a list of
    blocks (e.g. ``[{'type': 'text', 'text': '...'}]``) even without thinking.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif hasattr(block, "text") and isinstance(block.text, str):
                parts.append(block.text)
        return "".join(parts)
    raise TypeError(f"chat content must be a non-empty str, got {content!r}")
