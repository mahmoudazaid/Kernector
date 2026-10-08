"""Agent-backed Software Delivery orchestrate for chat-time tool runs.

When ``SOFTWARE_DELIVERY_AGENT_LOOP`` is on, composition injects this orchestrate
in place of the deterministic #170 chain. Pack imports stay lazy so
``import composition`` never loads a pack.

#309 retires scaffolding risk/generate/markdown-export bindings. The agent
exposes ``software_delivery.export_test_cases_google_drive`` when a Test Design
draft with selected titles is available. Destination defaults to My Drive Home
when none is persisted for the conversation.

Optional ``retrieve_tool`` (``knowledge.retrieve``) can be bound for
evidence-needing multi-tool turns; Drive-export wiring omits it so export
stays retrieval-free. Pre-orchestrate retrieve is deferred on the agent path
(``PackSoftwareDeliveryChat.defer_retrieval``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol

from application.response_style_policy import ResponseStyle, compose_agent_system
from application.run_tool_agent import RunToolAgent
from application.untrusted_text import AGENT_BOUNDARY, agent_tool_system_prompt
from domain.tool_approval import ApprovalHints
from composition.drive_export.prepare import (
    DraftUnavailable,
    ExportDestinationRequired,
    PreparedDriveExportCall,
    prepare_drive_export_call,
)
from composition.software_delivery.chat import OpaqueInvoke, Orchestrate
from composition.xray_export.prepare import TOOL_NAME as XRAY_PREPARED_TOOL_NAME
from composition.xray_export.prepare import (
    PreparedXrayExportCall,
    XrayDraftUnavailable,
)
from domain.knowledge import ScoredChunk
from domain.ports import Tool, ToolCallingAgent
from domain.tool_approval import PendingToolApproval

# Keep the tool name as a composition-local constant so this module never
# imports ``packs`` at load time (lazy boundary).
TOOL_NAME = "software_delivery.export_test_cases_google_drive"
XRAY_TOOL_NAME = XRAY_PREPARED_TOOL_NAME
_XRAY_TARGET = re.compile(r"\bxray\b", re.IGNORECASE)
_XRAY_UNAVAILABLE_SUMMARY = "Xray test creation is not available right now."
_XRAY_DRAFT_UNAVAILABLE_SUMMARY = (
    "I need a Test Design draft with generated test cases before I can create "
    "Xray tests."
)
_XRAY_PENDING_SUMMARY = (
    "I can create the generated Test Design cases as Xray tests in project "
    "{project_key}. Review the details and approve to continue."
)
_XRAY_FINISHED_SUMMARY = "Xray test creation finished."
_XRAY_CANCELLED_SUMMARY = (
    "Understood. I cancelled the request and did not create any Xray tests."
)
_XRAY_FIXED_ARGS_NOTE = (
    " The draft is fixed from the conversation’s Test Design workflow; do not "
    "invent or rely on tool parameters."
)

_DEFAULT_MAX_STEPS = 8
_NO_TOOLS_INVOKED = "No software-delivery tools were invoked."
_TRUNCATED_NOTE = " The agent stopped early before completing the requested tools."
_DESTINATION_REQUIRED_SUMMARY = (
    "I can’t prepare a Google Drive export yet. Save an export destination "
    "for this conversation, then ask again."
)
_PENDING_APPROVAL_SUMMARY = (
    "I can export the selected test cases as Markdown to your Google Drive "
    "destination. Review the details and approve to continue."
)
_CANCELLED_SUMMARY = (
    "Understood. I cancelled the export and did not write anything to Google Drive."
)
_EXPORT_FINISHED_SUMMARY = (
    "Export finished. The Markdown file is in your Google Drive destination."
)
_DRAFT_UNAVAILABLE_SUMMARY = (
    "I need a Test Design draft with selected titles before I can export to "
    "Google Drive."
)
_FIXED_ARGS_NOTE = (
    " Folder and titles are fixed from the conversation’s Test Design draft and "
    "destination (Home when unset); do not invent or rely on tool parameters."
)


class _DraftRepository(Protocol):
    def find_by_conversation_id(self, conversation_id: str) -> object | None: ...


class _DestinationRepository(Protocol):
    def get(self, conversation_id: str) -> object | None: ...


PrepareDriveExport = Callable[
    [str],
    PreparedDriveExportCall | ExportDestinationRequired | DraftUnavailable,
]
PrepareXrayExport = Callable[[str], PreparedXrayExportCall | XrayDraftUnavailable]


@dataclass(frozen=True, slots=True)
class ExportDestinationRequiredOutcome:
    """Chat projection: destination must be configured before interrupt/HITL."""

    outcome: str = "export_destination_required"


@dataclass(frozen=True, slots=True)
class ExportGoogleDriveOutcome:
    """Safe Drive export receipt for chat projection."""

    file_id: str
    file_name: str
    destination_label: str


@dataclass(frozen=True, slots=True)
class CreateXrayTestsOutcome:
    """Safe Xray creation receipt for chat projection (issue keys only)."""

    created_keys: tuple[str, ...]
    failed_count: int
    project_key: str


@dataclass(frozen=True, slots=True)
class AgentSoftwareDeliveryResponse:
    """Composition-authored orchestrate response for the agent export path."""

    summary: str
    outcomes: Sequence[object] = ()
    pending_approval: PendingToolApproval | None = None


@dataclass(frozen=True, slots=True)
class _BoundTool:
    """Domain ``Tool`` whose body calls opaque invoke with closed-over args."""

    _name: str
    _description: str
    _invoke: OpaqueInvoke
    _arguments: Mapping[str, object]
    _on_result: object  # Callable[[str], None]
    approval_hints: object | None = None
    args_schema: ClassVar[type | None] = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments
        result = self._invoke(self._name, self._arguments)
        self._on_result(result)  # type: ignore[operator]
        return result


def build_agent_orchestrate(
    agent: ToolCallingAgent,
    *,
    prepare_export: PrepareDriveExport | None = None,
    drafts: _DraftRepository | None = None,
    destinations: _DestinationRepository | None = None,
    max_steps: int = _DEFAULT_MAX_STEPS,
    retrieve_tool: Tool | None = None,
    prepare_xray: PrepareXrayExport | None = None,
) -> Orchestrate:
    """Return an ``orchestrate`` callable backed by ``agent``.

    Provide either ``prepare_export`` or both ``drafts`` and ``destinations``.
    Optional ``retrieve_tool`` is bound for evidence-needing multi-tool turns;
    Drive-export-only wiring omits it so export stays retrieval-free.
    Targets naming Xray bind only the Xray tool, and only when
    ``prepare_xray`` is wired (#199).
    """
    run_agent = RunToolAgent(agent)
    resolve = prepare_export
    if resolve is None:
        if drafts is None or destinations is None:
            raise ValueError(
                "prepare_export or both drafts and destinations are required"
            )

        def resolve(conversation_id: str):
            return prepare_drive_export_call(
                conversation_id=conversation_id,
                drafts=drafts,  # type: ignore[arg-type]
                destinations=destinations,  # type: ignore[arg-type]
            )

    def orchestrate(
        *,
        target: str,
        hits: Sequence[ScoredChunk],
        generate_tests: bool,
        output_style: str,
        invoke: OpaqueInvoke,
        conversation_id: str | None = None,
        response_style: ResponseStyle | None = None,
    ):
        del generate_tests, output_style
        is_xray = _XRAY_TARGET.search(target or "") is not None
        if conversation_id is None or not str(conversation_id).strip():
            return AgentSoftwareDeliveryResponse(
                summary=(
                    _XRAY_DRAFT_UNAVAILABLE_SUMMARY if is_xray else _DRAFT_UNAVAILABLE_SUMMARY
                ),
                outcomes=(),
            )
        style = response_style if isinstance(response_style, ResponseStyle) else None
        if is_xray:
            return _run_xray(
                run_agent,
                prepare_xray,
                conversation_id=str(conversation_id).strip(),
                invoke=invoke,
                max_steps=max_steps,
                style=style,
            )

        prepared = resolve(str(conversation_id).strip())
        if isinstance(prepared, ExportDestinationRequired):
            return AgentSoftwareDeliveryResponse(
                summary=_DESTINATION_REQUIRED_SUMMARY,
                outcomes=(ExportDestinationRequiredOutcome(),),
            )
        if isinstance(prepared, DraftUnavailable):
            return AgentSoftwareDeliveryResponse(
                summary=_DRAFT_UNAVAILABLE_SUMMARY,
                outcomes=(),
            )

        outcomes: list[object] = []

        def on_export(raw: str) -> None:
            outcomes.append(_parse_drive_receipt(raw, prepared.destination_label))

        tools: list[Tool] = []
        if retrieve_tool is not None:
            tools.append(retrieve_tool)
        tools.append(
            _BoundTool(
                prepared.tool_name,
                "Export selected Test Design titles to Google Drive as Markdown."
                + _FIXED_ARGS_NOTE,
                invoke,
                prepared.arguments,
                on_export,
                ApprovalHints(
                    title="Export test cases to Google Drive",
                    summary=(
                        "Write a Markdown file with the selected Test Design "
                        "titles. Arguments stay on the server; this card is a "
                        "safe preview only."
                    ),
                    destination_label=prepared.destination_label,
                    file_name=prepared.file_name,
                    selected_title_count=prepared.selected_title_count,
                ),
            )
        )
        goal = _agent_goal(target=target, hits=hits, prepared=prepared)
        turn = run_agent.execute(
            goal,
            tools,
            max_steps=max_steps,
            conversation_id=conversation_id,
            system_prompt=compose_agent_system(agent_tool_system_prompt(), style),
        )
        pending = getattr(turn, "pending_approval", None)
        if isinstance(pending, PendingToolApproval):
            return AgentSoftwareDeliveryResponse(
                summary=_PENDING_APPROVAL_SUMMARY,
                outcomes=(),
                pending_approval=pending,
            )
        if outcomes:
            summary = _EXPORT_FINISHED_SUMMARY
        else:
            summary = _NO_TOOLS_INVOKED
        if turn.truncated:
            summary = summary + _TRUNCATED_NOTE
        # Reject path: adapter returns cancelled content with no outcomes.
        if not outcomes and "cancel" in turn.content.lower():
            summary = _CANCELLED_SUMMARY
        return AgentSoftwareDeliveryResponse(
            summary=summary,
            outcomes=tuple(outcomes),
        )

    return orchestrate


def _run_xray(
    run_agent: RunToolAgent,
    prepare_xray: PrepareXrayExport | None,
    *,
    conversation_id: str,
    invoke: OpaqueInvoke,
    max_steps: int,
    style: ResponseStyle | None,
) -> AgentSoftwareDeliveryResponse:
    if prepare_xray is None:
        return AgentSoftwareDeliveryResponse(summary=_XRAY_UNAVAILABLE_SUMMARY)
    prepared = prepare_xray(conversation_id)
    if not isinstance(prepared, PreparedXrayExportCall):
        return AgentSoftwareDeliveryResponse(summary=_XRAY_DRAFT_UNAVAILABLE_SUMMARY)

    outcomes: list[object] = []

    def on_create(raw: str) -> None:
        outcomes.append(parse_xray_receipt(raw, prepared.project_key))

    tool = _BoundTool(
        prepared.tool_name,
        "Create the generated Test Design cases as Xray tests." + _XRAY_FIXED_ARGS_NOTE,
        invoke,
        prepared.arguments,
        on_create,
        ApprovalHints(
            title="Create Xray tests",
            summary=(
                "Create Jira Test issues in Xray from the generated Test Design "
                "cases. Each approval creates new tests; arguments stay on the server."
            ),
            destination_label=prepared.project_key,
            selected_title_count=prepared.test_count,
        ),
    )
    goal = (
        f"Task: Create {prepared.test_count} Xray tests from the conversation's "
        f"Test Design draft using the bound {prepared.tool_name} tool. "
        "Call that tool now; do not ask clarifying questions."
    )
    turn = run_agent.execute(
        goal,
        [tool],
        max_steps=max_steps,
        conversation_id=conversation_id,
        system_prompt=compose_agent_system(agent_tool_system_prompt(), style),
    )
    pending = getattr(turn, "pending_approval", None)
    if isinstance(pending, PendingToolApproval):
        return AgentSoftwareDeliveryResponse(
            summary=_XRAY_PENDING_SUMMARY.format(project_key=prepared.project_key),
            pending_approval=pending,
        )
    if outcomes:
        summary = _XRAY_FINISHED_SUMMARY
    elif "cancel" in turn.content.lower():
        summary = _XRAY_CANCELLED_SUMMARY
    else:
        summary = _NO_TOOLS_INVOKED
    if turn.truncated:
        summary = summary + _TRUNCATED_NOTE
    return AgentSoftwareDeliveryResponse(summary=summary, outcomes=tuple(outcomes))


def parse_xray_receipt(raw: str, project_key: str) -> CreateXrayTestsOutcome:
    """Read the tool's JSON summary; malformed input yields an empty receipt."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return CreateXrayTestsOutcome(created_keys=(), failed_count=0, project_key=project_key)
    keys = payload.get("created_keys")
    failed = payload.get("failed_count")
    return CreateXrayTestsOutcome(
        created_keys=(
            tuple(key for key in keys if isinstance(key, str)) if isinstance(keys, list) else ()
        ),
        failed_count=failed if isinstance(failed, int) and not isinstance(failed, bool) else 0,
        project_key=project_key,
    )


def _parse_drive_receipt(raw: str, destination_label: str) -> ExportGoogleDriveOutcome:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return ExportGoogleDriveOutcome(
            file_id="",
            file_name="",
            destination_label=destination_label,
        )
    if not isinstance(payload, dict):
        return ExportGoogleDriveOutcome(
            file_id="",
            file_name="",
            destination_label=destination_label,
        )
    file_id = payload.get("file_id")
    file_name = payload.get("file_name")
    return ExportGoogleDriveOutcome(
        file_id=file_id if isinstance(file_id, str) else "",
        file_name=file_name if isinstance(file_name, str) else "",
        destination_label=destination_label,
    )


def _agent_goal(
    *,
    target: str,
    hits: Sequence[ScoredChunk],
    prepared: PreparedDriveExportCall,
) -> str:
    snippets = []
    for hit in hits[:8]:
        ref = hit.chunk.reference
        payload = (
            f"[source_type={ref.source_type} source_id={ref.source_id}]\n"
            f"{hit.chunk.content[:400]}"
        )
        snippets.append(
            AGENT_BOUNDARY.wrap("evidence", payload, include_notice=True)
        )
    evidence_block = "\n".join(snippets) if snippets else "(no snippets)"
    task = (
        f"Export {prepared.selected_title_count} selected Test Design titles "
        f"to Google Drive using the bound {TOOL_NAME} tool. "
        "Call that tool now; do not ask clarifying questions."
    )
    return (
        f"{AGENT_BOUNDARY.wrap('target', target, include_notice=True)}\n\n"
        f"Task: {task}\n\n"
        f"Evidence snippets:\n{evidence_block}"
    )
