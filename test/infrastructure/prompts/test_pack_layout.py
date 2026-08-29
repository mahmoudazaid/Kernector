"""Pack layout: core default pack and optional Story Intelligence pack."""

import re
from pathlib import Path

from infrastructure.prompts.markdown_repository import MarkdownPromptRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_ROOT = REPO_ROOT / "prompts"
CORE_PACK = PROMPTS_ROOT / "packs" / "core"
STORY_INTELLIGENCE_PACK = PROMPTS_ROOT / "packs" / "story-intelligence"

EXPECTED_STORY_FILES = (
    "role-q-a.md",
    "star-answer-coach.md",
    "ask-interviewer.md",
    "jd-analyser.md",
    "pitch-polisher.md",
)
EXPECTED_STORY_KEYS = {
    "role_qa",
    "star_coach",
    "ask_interviewer",
    "jd_analyser",
    "pitch_polisher",
}

DOMAIN_DENYLIST = (
    "interview",
    "story",
    "ticket",
    "star",
    "job description",
    "recruiter",
)


def test_story_intelligence_pack_holds_interview_prompts_not_root() -> None:
    assert list(PROMPTS_ROOT.glob("*.md")) == []
    for filename in EXPECTED_STORY_FILES:
        assert (STORY_INTELLIGENCE_PACK / filename).is_file()

    repository = MarkdownPromptRepository((STORY_INTELLIGENCE_PACK,))
    prompts = repository.all()
    assert set(prompts) == EXPECTED_STORY_KEYS
    assert repository.default_key() == "role_qa"


def test_core_pack_holds_neutral_default_prompt() -> None:
    assert list(PROMPTS_ROOT.glob("*.md")) == []
    assert (CORE_PACK / "knowledge-qa.md").is_file()

    repository = MarkdownPromptRepository((CORE_PACK,))
    prompts = repository.all()
    assert set(prompts) == {"knowledge_qa"}
    assert repository.default_key() == "knowledge_qa"

    text = (CORE_PACK / "knowledge-qa.md").read_text(encoding="utf-8")
    for term in DOMAIN_DENYLIST:
        assert re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE) is None, (
            f"core pack must not contain {term!r}"
        )
