"""Pure projection of session messages into safe export formats."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExportTurn:
    """One conversation turn safe for export (no tool payloads or secrets)."""

    role: str
    content: str
    timestamp: str = ""
    request_id: str = ""
    tools: tuple[str, ...] = ()


def _project_message(message: Mapping[str, Any]) -> ExportTurn | None:
    if message.get("display_only"):
        return None
    role = message.get("role")
    content = message.get("content")
    if role not in ("user", "assistant") or not isinstance(content, str):
        return None
    if not content.strip():
        return None

    request_id = ""
    tools: tuple[str, ...] = ()
    run = message.get("run")
    if run is not None:
        rid = getattr(run, "request_id", None)
        if isinstance(rid, str) and rid.strip():
            request_id = rid
        raw_tools = getattr(run, "tools", ()) or ()
        tools = tuple(
            name for name in raw_tools if isinstance(name, str) and name.strip()
        )

    timestamp = message.get("timestamp")
    if not isinstance(timestamp, str):
        timestamp = ""

    return ExportTurn(
        role=role,
        content=content,
        timestamp=timestamp,
        request_id=request_id,
        tools=tools,
    )


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
    """Serialize export turns as a JSON array string."""
    payload = [
        {
            "role": turn.role,
            "content": turn.content,
            "timestamp": turn.timestamp,
            "request_id": turn.request_id,
            "tools": list(turn.tools),
        }
        for turn in turns
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def conversation_to_csv(turns: Sequence[ExportTurn]) -> str:
    """Serialize export turns as CSV with role/content/timestamp/request_id."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["role", "content", "timestamp", "request_id"])
    for turn in turns:
        writer.writerow([turn.role, turn.content, turn.timestamp, turn.request_id])
    return buffer.getvalue()


def conversation_to_markdown(turns: Sequence[ExportTurn]) -> str:
    """Serialize export turns as a readable Markdown transcript."""
    blocks: list[str] = []
    for turn in turns:
        blocks.append(f"### {turn.role}\n\n{turn.content}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def turns_for_pdf(turns: Sequence[ExportTurn]) -> tuple[dict[str, str], ...]:
    """Map export turns to the role/content dicts the PDF builder accepts."""
    return tuple({"role": turn.role, "content": turn.content} for turn in turns)
