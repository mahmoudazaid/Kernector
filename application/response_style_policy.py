"""Allowlisted response-style presets as application prompt policy.

Formal, Friendly, and Concise adjust wording and length only. They never
change retrieval, citations, safety rules, tool selection, or tool arguments.
Prompt text is data — never executed as code.

``Default`` is UI-only: callers omit style (``None``) and composition returns
the base system prompt unchanged.
"""

from __future__ import annotations

from enum import StrEnum

from application.grounded_rag_policy import GROUNDED_RAG_SYSTEM


class ResponseStyle(StrEnum):
    """Wire and application values for selectable response style."""

    FORMAL = "formal"
    FRIENDLY = "friendly"
    CONCISE = "concise"


FORMAL_STYLE_INSTRUCTION = (
    "Response style: Formal.\n"
    "- Use professional, neutral language and complete sentences.\n"
    "- Prefer precise terminology; avoid contractions and conversational "
    "filler.\n"
    "- Preserve every fact and citation from the evidence; do not invent "
    "details.\n"
    "- Do not change grounding, citations, safety rules, tool selection, or "
    "tool arguments."
)

FRIENDLY_STYLE_INSTRUCTION = (
    "Response style: Friendly.\n"
    "- Use warm, conversational plain language and address the user directly "
    "(you/your).\n"
    "- Contractions are fine. Begin with a short natural explanatory phrase "
    "(for example: \"Here's what I found:\" or \"In short:\").\n"
    "- No emojis and no exaggerated enthusiasm.\n"
    "- Preserve every fact and citation from the evidence; do not invent "
    "details.\n"
    "- Do not change grounding, citations, safety rules, tool selection, or "
    "tool arguments."
)

CONCISE_STYLE_INSTRUCTION = (
    "Response style: Concise.\n"
    "- Answer directly in at most three sentences unless the user asks for "
    "more detail.\n"
    "- No preamble, no restating the question, and no repetition.\n"
    "- Preserve every fact and citation from the evidence; do not invent "
    "details.\n"
    "- Do not change grounding, citations, safety rules, tool selection, or "
    "tool arguments."
)

_STYLE_INSTRUCTIONS: dict[ResponseStyle, str] = {
    ResponseStyle.FORMAL: FORMAL_STYLE_INSTRUCTION,
    ResponseStyle.FRIENDLY: FRIENDLY_STYLE_INSTRUCTION,
    ResponseStyle.CONCISE: CONCISE_STYLE_INSTRUCTION,
}


def style_instruction(style: ResponseStyle | None) -> str | None:
    """Return the fixed style instruction, or ``None`` when unset."""
    if style is None:
        return None
    return _STYLE_INSTRUCTIONS[style]


def compose_grounded_system(style: ResponseStyle | None) -> str:
    """Compose grounded system text for one ask without mutating the constant.

    Returns:
        str: ``GROUNDED_RAG_SYSTEM`` alone when ``style`` is ``None`` (same
        object identity), otherwise the policy plus the allowlisted style
        instruction.
    """
    instruction = style_instruction(style)
    if instruction is None:
        return GROUNDED_RAG_SYSTEM
    return f"{GROUNDED_RAG_SYSTEM}\n\n{instruction}"


def compose_agent_system(base: str, style: ResponseStyle | None) -> str:
    """Append an allowlisted style instruction to an agent base system prompt.

    Args:
        base (str): Style-free agent system prompt for this path.
        style (ResponseStyle | None): Optional response-style preset.

    Returns:
        str: ``base`` unchanged when ``style`` is ``None``, otherwise
        ``base`` plus the fixed style instruction.
    """
    instruction = style_instruction(style)
    if instruction is None:
        return base
    return f"{base}\n\n{instruction}"
