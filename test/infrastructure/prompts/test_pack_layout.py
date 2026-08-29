"""Migration layout: Story Intelligence pack holds interview prompts."""

from pathlib import Path

from infrastructure.prompts.markdown_repository import MarkdownPromptRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_ROOT = REPO_ROOT / "prompts"
STORY_INTELLIGENCE_PACK = PROMPTS_ROOT / "packs" / "story-intelligence"

EXPECTED_FILES = (
    "role-q-a.md",
    "star-answer-coach.md",
    "ask-interviewer.md",
    "jd-analyser.md",
    "pitch-polisher.md",
)
EXPECTED_KEYS = {
    "role_qa",
    "star_coach",
    "ask_interviewer",
    "jd_analyser",
    "pitch_polisher",
}


def test_story_intelligence_pack_holds_interview_prompts_not_root() -> None:
    assert list(PROMPTS_ROOT.glob("*.md")) == []
    for filename in EXPECTED_FILES:
        assert (STORY_INTELLIGENCE_PACK / filename).is_file()

    repository = MarkdownPromptRepository((STORY_INTELLIGENCE_PACK,))
    prompts = repository.all()
    assert set(prompts) == EXPECTED_KEYS
    assert repository.default_key() == "role_qa"
