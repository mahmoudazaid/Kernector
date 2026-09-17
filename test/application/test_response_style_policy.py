"""Response-style presets are allowlisted prompt data in application policy."""

from application.grounded_rag_policy import GROUNDED_RAG_SYSTEM
from application.response_style_policy import (
    FORMAL_STYLE_INSTRUCTION,
    FRIENDLY_STYLE_INSTRUCTION,
    CONCISE_STYLE_INSTRUCTION,
    ResponseStyle,
    compose_agent_system,
    compose_grounded_system,
    style_instruction,
)

# Exact trusted prompt strings — independent of composition helpers.
_EXPECTED_FORMAL = (
    "Response style: Formal.\n"
    "- Use professional, neutral language and complete sentences.\n"
    "- Prefer precise terminology; avoid contractions and conversational "
    "filler.\n"
    "- Preserve every fact and citation from the evidence; do not invent "
    "details.\n"
    "- Do not change grounding, citations, safety rules, tool selection, or "
    "tool arguments."
)
_EXPECTED_FRIENDLY = (
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
_EXPECTED_CONCISE = (
    "Response style: Concise.\n"
    "- Answer directly in at most three sentences unless the user asks for "
    "more detail.\n"
    "- No preamble, no restating the question, and no repetition.\n"
    "- Preserve every fact and citation from the evidence; do not invent "
    "details.\n"
    "- Do not change grounding, citations, safety rules, tool selection, or "
    "tool arguments."
)


def test_style_instruction_returns_none_when_unset() -> None:
    assert style_instruction(None) is None


def test_style_instruction_literals_match_exact_trusted_prompts() -> None:
    assert FORMAL_STYLE_INSTRUCTION == _EXPECTED_FORMAL
    assert FRIENDLY_STYLE_INSTRUCTION == _EXPECTED_FRIENDLY
    assert CONCISE_STYLE_INSTRUCTION == _EXPECTED_CONCISE
    assert style_instruction(ResponseStyle.FORMAL) == _EXPECTED_FORMAL
    assert style_instruction(ResponseStyle.FRIENDLY) == _EXPECTED_FRIENDLY
    assert style_instruction(ResponseStyle.CONCISE) == _EXPECTED_CONCISE


def test_style_instructions_are_observably_distinct() -> None:
    formal = style_instruction(ResponseStyle.FORMAL)
    friendly = style_instruction(ResponseStyle.FRIENDLY)
    concise = style_instruction(ResponseStyle.CONCISE)
    assert formal != friendly != concise
    assert formal is not None and "contractions" in formal.lower()
    assert friendly is not None and "address the user" in friendly.lower()
    assert concise is not None and "three sentences" in concise.lower()


def test_compose_grounded_system_without_style_is_the_policy_constant() -> None:
    assert compose_grounded_system(None) is GROUNDED_RAG_SYSTEM
    assert compose_grounded_system(None) == GROUNDED_RAG_SYSTEM


def test_compose_grounded_system_appends_exact_style_without_mutating_constant() -> None:
    before = GROUNDED_RAG_SYSTEM
    composed = compose_grounded_system(ResponseStyle.FORMAL)

    assert composed == f"{GROUNDED_RAG_SYSTEM}\n\n{_EXPECTED_FORMAL}"
    assert GROUNDED_RAG_SYSTEM == before
    assert GROUNDED_RAG_SYSTEM is before
    assert _EXPECTED_FORMAL not in GROUNDED_RAG_SYSTEM


def test_compose_agent_system_appends_exact_style_to_base() -> None:
    base = "You are a tool-calling agent."
    composed = compose_agent_system(base, ResponseStyle.CONCISE)

    assert composed == f"{base}\n\n{_EXPECTED_CONCISE}"
    assert compose_agent_system(base, None) == base
