"""Pure Mode selection helpers for the Streamlit sidebar."""

from collections.abc import Mapping, Sequence

from domain.models import PromptVariant

ModeOption = tuple[str | None, str]


def mode_options(prompts: Mapping[str, PromptVariant]) -> list[ModeOption]:
    """Return selectable Modes with General (no task prompt) first."""
    return [(None, "General"), *((key, prompt.name) for key, prompt in prompts.items())]


def default_mode_index(options: Sequence[ModeOption]) -> int:
    """Index of the default Mode — always General when present."""
    for index, (key, _label) in enumerate(options):
        if key is None:
            return index
    return 0
