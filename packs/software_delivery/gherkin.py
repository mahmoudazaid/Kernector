"""Gherkin Scenario-step phase validation for test-case generation."""

from __future__ import annotations

from collections.abc import Sequence

_PHASE_KEYWORDS = frozenset({"Given", "When", "Then"})
_CONTINUATION_KEYWORDS = frozenset({"And", "But"})
_ALL_KEYWORDS = _PHASE_KEYWORDS | _CONTINUATION_KEYWORDS
_PHASE_ORDER = {"Given": 0, "When": 1, "Then": 2}


def parse_gherkin_steps(steps: Sequence[str]) -> tuple[tuple[str, ...], str]:
    """Validate ordered Gherkin phases and derive expected from the terminal Then.

    Returns:
        Normalized step strings (unchanged) and expected text derived from every
        assertion body in the terminal Then phase, joined by newlines.

    Raises:
        ValueError: Structural Gherkin violation (caller maps to ToolFailureError).
    """
    if isinstance(steps, (str, bytes)) or not isinstance(steps, Sequence):
        raise ValueError(f"steps must be a sequence, got {steps!r}")
    if len(steps) == 0:
        raise ValueError("steps must be non-empty")

    current_phase: str | None = None
    seen_phases: set[str] = set()
    terminal_bodies: list[str] = []
    normalized: list[str] = []

    for raw in steps:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("steps items must be non-empty strings")
        keyword, body = _split_step(raw)
        if keyword in _CONTINUATION_KEYWORDS:
            if current_phase is None:
                raise ValueError(
                    f"leading or orphan {keyword} is invalid before a phase keyword"
                )
            phase = current_phase
        else:
            phase = keyword
            prior = _PHASE_ORDER[current_phase] if current_phase is not None else -1
            if _PHASE_ORDER[phase] < prior:
                raise ValueError(
                    f"phase regression: cannot move from {current_phase} to {phase}"
                )
            if _PHASE_ORDER[phase] > prior + 1 and prior >= 0:
                # Skipping a phase (e.g. Given -> Then) is missing When.
                missing = [
                    name
                    for name, order in _PHASE_ORDER.items()
                    if prior < order < _PHASE_ORDER[phase]
                ]
                raise ValueError(f"missing phase(s): {', '.join(missing)}")
            if current_phase is None and phase != "Given":
                raise ValueError("scenario must start with Given")
            current_phase = phase
            seen_phases.add(phase)

        if not body.strip():
            raise ValueError(f"{keyword} body must be non-empty")
        normalized.append(f"{keyword} {body}")
        if phase == "Then":
            terminal_bodies.append(body)

    missing = [name for name in ("Given", "When", "Then") if name not in seen_phases]
    if missing:
        raise ValueError(f"missing phase(s): {', '.join(missing)}")
    if not terminal_bodies:
        raise ValueError("missing Then phase")
    expected = "\n".join(terminal_bodies)
    return tuple(normalized), expected


def _split_step(step: str) -> tuple[str, str]:
    stripped = step.strip()
    for keyword in sorted(_ALL_KEYWORDS, key=len, reverse=True):
        if stripped == keyword:
            return keyword, ""
        prefix = f"{keyword} "
        if stripped.startswith(prefix):
            return keyword, stripped[len(prefix) :]
    raise ValueError(
        "each gherkin step must start with Given, When, Then, And, or But"
    )
