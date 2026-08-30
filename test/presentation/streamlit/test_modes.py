"""Mode selection for grounded chat (General vs optional task prompts).

Uses synthetic variants throughout. The reusable core is domain-agnostic
(ADR 0001), so Mode selection must be provable without naming a shipped pack —
which shipped packs exist is pinned by ``test_pack_layout.py`` instead.
"""

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
        "alpha_mode": _variant("alpha_mode", "Alpha Mode"),
        "beta_mode": _variant("beta_mode", "Beta Mode"),
    }

    assert mode_options(prompts) == [
        (None, "General"),
        ("alpha_mode", "Alpha Mode"),
        ("beta_mode", "Beta Mode"),
    ]


def test_default_mode_is_general_not_the_first_pack_variant() -> None:
    options = mode_options({"alpha_mode": _variant("alpha_mode", "Alpha Mode")})
    index = default_mode_index(options)
    assert options[index] == (None, "General")


def test_general_stays_distinct_from_a_blank_keyed_variant() -> None:
    """Nothing validates prompt keys as non-blank, so a pack whose frontmatter
    reads `key:` yields "". General is identified by `None`, never by a string
    sentinel that such a variant could collide with."""
    options = mode_options({"": _variant("", "Blank Keyed")})

    assert options == [(None, "General"), ("", "Blank Keyed")]
    assert len({key for key, _label in options}) == 2
    assert options[default_mode_index(options)] == (None, "General")
