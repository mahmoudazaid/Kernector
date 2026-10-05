"""Test Design system prompts stored as Markdown templates (ADR 0009)."""

from __future__ import annotations

from importlib.resources import files
from string import Template


def load_prompt(name: str, **values: object) -> str:
    """Render the ``<name>.md`` template in this package.

    Placeholders use ``$NAME`` syntax. Rendering is strict in both directions
    so a renamed placeholder fails at import instead of reaching the model.

    Args:
        name (str): Template file name without the ``.md`` suffix.
        **values (object): Value for every ``$NAME`` placeholder in the file.

    Returns:
        str: The rendered prompt text.

    Raises:
        FileNotFoundError: No template named ``name`` exists.
        KeyError: The template uses a placeholder with no supplied value.
        ValueError: A supplied value has no placeholder in the template.
    """
    template = Template(
        files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")
    )
    used = set(template.get_identifiers())
    for key in sorted(values):
        if key not in used:
            raise ValueError(f"{name}.md has no ${key} placeholder")
    return template.substitute(values)
