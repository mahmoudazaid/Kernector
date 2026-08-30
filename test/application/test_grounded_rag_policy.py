"""The grounded-RAG policy is mandatory, non-selectable, and domain-neutral.

Deliberately not a keyword checklist over the prose. Asserting that the text
contains the words its own author just wrote passes any rewording that keeps
four keywords and fails on a legitimate synonym — it tracks vocabulary, not
behaviour. What the policy must actually guarantee is checked in
``test_ask_knowledge.py``, where the constant is observed reaching the model
intact through a fake ``ChatModel``. What is left here are the structural
properties no other test covers.
"""

from pathlib import Path

from application.grounded_rag_policy import (
    CONTEXT_CLOSE,
    CONTEXT_OPEN,
    GROUNDED_RAG_SYSTEM,
    INSUFFICIENT_KNOWLEDGE_ANSWER,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Vocabulary from the shipped packs. The reusable core is domain-agnostic
# (ADR 0001), so platform policy may not name a product surface.
PACK_VOCABULARY = (
    "story intelligence",
    "story-intelligence",
    "interview",
    "jira",
    "ticket",
    "sprint",
    "sdlc",
    "resume",
    "candidate",
)


def test_policy_declares_the_context_delimiters_it_relies_on() -> None:
    """The delimiters are a contract between the policy and the message builder.
    If they drift apart, the policy names markers the context never carries and
    the untrusted-data rule silently describes nothing."""
    assert CONTEXT_OPEN in GROUNDED_RAG_SYSTEM
    assert CONTEXT_CLOSE in GROUNDED_RAG_SYSTEM
    assert CONTEXT_OPEN != CONTEXT_CLOSE


def test_policy_is_domain_neutral() -> None:
    text = GROUNDED_RAG_SYSTEM.lower()
    named = [term for term in PACK_VOCABULARY if term in text]
    assert not named, f"policy names pack-specific vocabulary: {named}"


def test_insufficient_answer_is_domain_neutral_and_non_blank() -> None:
    text = INSUFFICIENT_KNOWLEDGE_ANSWER.lower()
    assert INSUFFICIENT_KNOWLEDGE_ANSWER.strip()
    assert not [term for term in PACK_VOCABULARY if term in text]


def test_policy_is_not_reachable_as_a_selectable_pack_prompt() -> None:
    """`PROMPT_PACKS` must not be able to shadow, disable, or re-offer the
    policy: it is a module constant precisely so no pack file can own it."""
    pack_bodies = [
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "prompts" / "packs").rglob("*.md")
    ]
    assert pack_bodies, "expected shipped prompt packs to exist"
    assert not [body for body in pack_bodies if GROUNDED_RAG_SYSTEM in body]
