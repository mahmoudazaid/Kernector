"""Mode selection for grounded chat (General vs optional task prompts)."""

from domain.models import PromptVariant
from presentation.streamlit.modes import default_mode_index, mode_options


def _variant(key: str, name: str) -> PromptVariant:
    return PromptVariant(
        key=key,
        name=name,
        description=f"{name} description",
        system=f"system for {key}",
    )


def test_mode_options_put_general_first_without_requiring_packs() -> None:
    assert mode_options({}) == [(None, "General")]


def test_mode_options_list_general_then_pack_variants() -> None:
    prompts = {
        "knowledge_qa": _variant("knowledge_qa", "Knowledge Q&A"),
        "role_qa": _variant("role_qa", "Role Q&A"),
    }

    assert mode_options(prompts) == [
        (None, "General"),
        ("knowledge_qa", "Knowledge Q&A"),
        ("role_qa", "Role Q&A"),
    ]


def test_default_mode_is_general_not_knowledge_qa() -> None:
    options = mode_options(
        {"knowledge_qa": _variant("knowledge_qa", "Knowledge Q&A")}
    )
    index = default_mode_index(options)
    assert options[index] == (None, "General")
