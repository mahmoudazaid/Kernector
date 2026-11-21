"""Unit coverage for _ElicitationGate back-channel / protocol branching."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import types

from domain.tool_approval import ApprovalDeferredError, PendingToolApproval
from presentation.mcp.app import _ApprovalInputRequired, _ElicitationGate


def _pending() -> PendingToolApproval:
    return PendingToolApproval(
        "a1",
        "fake.create",
        "Create things",
        "Creates new things.",
        destination_label="QA",
        selected_title_count=1,
        item_titles=("One",),
    )


def _gate(*, protocol: str, can_send_request: bool) -> _ElicitationGate:
    session = SimpleNamespace(
        can_send_request=can_send_request,
        protocol_version=protocol,
    )
    ctx = SimpleNamespace(protocol_version=protocol, session=session, request_id="1")
    params = types.CallToolRequestParams(name="fake_create_things", arguments={"x": 1})
    return _ElicitationGate(ctx, params, {"x": 1})  # type: ignore[arg-type]


def test_handshake_without_backchannel_fails_closed_as_approval_required() -> None:
    """json_response mode: do not emit InputRequiredResult on handshake versions."""
    gate = _gate(protocol="2025-11-25", can_send_request=False)

    with pytest.raises(ApprovalDeferredError) as raised:
        gate(_pending())

    assert not isinstance(raised.value, _ApprovalInputRequired)
    assert gate.input_required() is None


def test_modern_without_backchannel_still_uses_input_required() -> None:
    gate = _gate(protocol="2026-07-28", can_send_request=False)

    with pytest.raises(_ApprovalInputRequired):
        gate(_pending())

    assert gate.input_required() is not None
