"""Pure projection of session messages into safe conversation export formats."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# OWASP CSV Injection: neutralize cells that Excel/LibreOffice may treat as formulas.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


@dataclass(frozen=True, slots=True)
class ExportTurn:
    """One conversation turn safe for export (role/content/timestamp only)."""

    role: str
    content: str
    timestamp: str = ""


def _project_message(message: Mapping[str, Any]) -> ExportTurn | None:
    if message.get("display_only"):
        return None
    role = message.get("role")
    content = message.get("content")
    if role not in ("user", "assistant") or not isinstance(content, str):
        return None
    if not content.strip():
        return None
    timestamp = message.get("timestamp")
    if not isinstance(timestamp, str):
        timestamp = ""
    return ExportTurn(role=role, content=content, timestamp=timestamp)


def project_conversation_turns(
    session_messages: Sequence[Mapping[str, Any]],
) -> tuple[ExportTurn, ...]:
    """Project all non-display-only user/assistant turns for export."""
    turns: list[ExportTurn] = []
    for message in session_messages:
        projected = _project_message(message)
        if projected is not None:
            turns.append(projected)
    return tuple(turns)


def project_single_turn(
    session_messages: Sequence[Mapping[str, Any]],
    index: int,
) -> tuple[ExportTurn, ...]:
    """Project one session message by index for per-turn export."""
    if index < 0 or index >= len(session_messages):
        return ()
    projected = _project_message(session_messages[index])
    if projected is None:
        return ()
    return (projected,)


def conversation_to_json(turns: Sequence[ExportTurn]) -> str:
    """Serialize export turns as a JSON array of role/content/timestamp."""
    payload = [
        {
            "role": turn.role,
            "content": turn.content,
            "timestamp": turn.timestamp,
        }
        for turn in turns
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def conversation_to_markdown(turns: Sequence[ExportTurn]) -> str:
    """Serialize export turns as a readable Markdown transcript."""
    blocks: list[str] = []
    for turn in turns:
        blocks.append(f"### {turn.role}\n\n{turn.content}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def neutralize_csv_formula(value: str) -> str:
    """Prefix formula-dangerous cells so spreadsheets treat them as text.

    See https://owasp.org/www-community/attacks/CSV_Injection
    """
    if value and value[0] in _CSV_FORMULA_PREFIXES:
        return f"'{value}"
    return value


def conversation_to_csv(turns: Sequence[ExportTurn]) -> str:
    """Serialize turns as CSV with role/content/timestamp; formula-safe cells."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["role", "content", "timestamp"])
    for turn in turns:
        writer.writerow(
            [
                neutralize_csv_formula(turn.role),
                neutralize_csv_formula(turn.content),
                neutralize_csv_formula(turn.timestamp),
            ]
        )
    return buffer.getvalue()


def turns_for_pdf(turns: Sequence[ExportTurn]) -> tuple[dict[str, str], ...]:
    """Map export turns to role/content dicts for the PDF builder."""
    return tuple({"role": turn.role, "content": turn.content} for turn in turns)
