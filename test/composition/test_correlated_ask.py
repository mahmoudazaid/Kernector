"""Composition correlation wrapper around any GroundedAsk."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from application import observability
from application.contracts import AskRequest, AskResponse, RunMeta
from application.errors import InsufficientEvidenceError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from composition.correlated_ask import CorrelatedAsk
from composition.tool_augmented_ask import ToolAugmentedAsk, ToolRunOutcome
from test.log_record import operation_payload, operation_records


@dataclass(frozen=True)
class _Selection:
    generate_tests: bool = False
    output_style: str = "steps"


class _AskCapturingRequestId:
    def __init__(self, response: AskResponse | None = None) -> None:
        self.response = response or AskResponse(answer="grounded answer")
        self.seen_request_id: str | None = None
        self.calls: list[AskRequest] = []

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        self.seen_request_id = observability.current_request_id()
        self.calls.append(request)
        return self.response


class _FailingAsk:
    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        raise RuntimeError("provider boom")


def test_correlated_ask_forwards_consume_tool_run_view() -> None:
    from composition.software_delivery_tools import SoftwareDeliveryRunView

    run_view = SoftwareDeliveryRunView(summary="Scored risk.", calls=())

    class _Inner:
        def __init__(self) -> None:
            self._view = run_view

        def execute(
            self,
            request: AskRequest,
            settings: Mapping[str, object] | None = None,
        ) -> AskResponse:
            return AskResponse(answer="ok", run=RunMeta(outcome="success", path="tools"))

        def consume_tool_run_view(self) -> SoftwareDeliveryRunView | None:
            view = self._view
            self._view = None
            return view

    ask = CorrelatedAsk(_Inner())  # type: ignore[arg-type]
    ask.execute(AskRequest(query="Score the risk for AUTH-101", prompt_key=None))

    assert ask.consume_tool_run_view() is run_view
    assert ask.consume_tool_run_view() is None


def test_correlated_ask_binds_request_id_for_zero_pack_chat() -> None:
    inner = _AskCapturingRequestId()
    ask = CorrelatedAsk(inner)

    response = ask.execute(AskRequest(query="What is the session timeout?", prompt_key=None))

    assert response.answer == "grounded answer"
    assert inner.seen_request_id is not None
    assert response.run is not None
    assert response.run.request_id == inner.seen_request_id
    assert observability.current_request_id() is None


def test_correlated_ask_stamps_request_id_when_inner_run_is_missing() -> None:
    inner = _AskCapturingRequestId(AskResponse(answer="insufficient"))
    ask = CorrelatedAsk(inner)

    response = ask.execute(AskRequest(query="unknown", prompt_key=None))

    assert response.run is not None
    assert response.run.request_id == inner.seen_request_id
    assert len(response.run.request_id or "") == 32


def test_correlated_ask_preserves_inner_run_fields_when_stamping() -> None:
    inner = _AskCapturingRequestId(
        AskResponse(
            answer="ok",
            run=RunMeta(outcome="success", hit_count=2, model="m"),
        )
    )
    ask = CorrelatedAsk(inner)

    response = ask.execute(AskRequest(query="hello", prompt_key=None))

    assert response.run is not None
    assert response.run.request_id == inner.seen_request_id
    assert response.run.outcome == "success"
    assert response.run.hit_count == 2
    assert response.run.model == "m"


def test_correlated_ask_reuses_prebound_outer_id_and_leaves_it_bound() -> None:
    inner = _AskCapturingRequestId()
    ask = CorrelatedAsk(inner)
    outer, token = observability.bind_request_id("req-outer-turn")
    try:
        ask.execute(AskRequest(query="hello", prompt_key=None))
        assert inner.seen_request_id == outer
        assert observability.current_request_id() == outer
    finally:
        observability.reset_request_id(token)
    assert observability.current_request_id() is None


def test_correlated_ask_restores_outer_context_when_inner_raises() -> None:
    ask = CorrelatedAsk(_FailingAsk())
    outer, token = observability.bind_request_id("req-outer-turn")
    try:
        with pytest.raises(RuntimeError, match="provider boom"):
            ask.execute(AskRequest(query="hello", prompt_key=None))
        assert observability.current_request_id() == outer
    finally:
        observability.reset_request_id(token)


def test_pack_nested_ops_share_one_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, str | None] = {}

    class _Runner:
        def run(
            self,
            target: str,
            *,
            generate_tests: bool = True,
            output_style: str = "steps",
        ) -> ToolRunOutcome:
            seen["runner"] = observability.current_request_id()
            return ToolRunOutcome(answer="ok")

    class _Ask:
        def execute(
            self,
            request: AskRequest,
            settings: Mapping[str, object] | None = None,
        ) -> AskResponse:
            seen["ask"] = observability.current_request_id()
            return AskResponse(answer="rag")

    routed = ToolAugmentedAsk(
        _Ask(),
        runner=_Runner(),
        select=lambda query: _Selection(),
        pack_id="software-delivery",
    )
    ask = CorrelatedAsk(routed)
    with caplog.at_level(logging.INFO):
        ask.execute(AskRequest(query="Score risk", prompt_key=None))

    assert seen["runner"] is not None
    assert seen.get("ask") is None
    records = operation_records(caplog.records, operation="ask_turn")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["request_id"] == seen["runner"]
    assert payload["path"] == "tools"
    assert payload["pack"] == "software-delivery"
    assert payload["outcome"] == "success"


def test_rag_delegation_logs_delegated_not_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _InsufficientAsk:
        def execute(
            self,
            request: AskRequest,
            settings: Mapping[str, object] | None = None,
        ) -> AskResponse:
            return AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER)

    routed = ToolAugmentedAsk(
        _InsufficientAsk(),
        runner=_RunnerNever(),
        select=lambda query: None,
        pack_id="software-delivery",
    )
    with caplog.at_level(logging.INFO, logger="composition.tool_augmented_ask"):
        response = routed.execute(
            AskRequest(query="What is the session timeout?", prompt_key=None)
        )

    assert response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
    records = operation_records(caplog.records, operation="ask_turn")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "delegated"
    assert payload["path"] == "rag"
    assert payload.get("pack") is None


def test_tools_insufficient_logs_insufficient_with_pack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Ask:
        def execute(
            self,
            request: AskRequest,
            settings: Mapping[str, object] | None = None,
        ) -> AskResponse:
            return AskResponse(answer="should not run")

    class _InsufficientRunner:
        def run(
            self,
            target: str,
            *,
            generate_tests: bool = True,
            output_style: str = "steps",
        ) -> ToolRunOutcome:
            raise InsufficientEvidenceError()

    @dataclass(frozen=True)
    class _Selection:
        generate_tests: bool = False
        output_style: str = "steps"

    routed = ToolAugmentedAsk(
        _Ask(),
        runner=_InsufficientRunner(),
        select=lambda query: _Selection(),
        pack_id="software-delivery",
    )
    with caplog.at_level(logging.INFO, logger="composition.tool_augmented_ask"):
        response = routed.execute(
            AskRequest(query="Assess the risk for AUTH-101", prompt_key=None)
        )

    assert response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
    payload = operation_payload(
        operation_records(caplog.records, operation="ask_turn")[0]
    )
    assert payload["outcome"] == "insufficient"
    assert payload["path"] == "tools"
    assert payload["pack"] == "software-delivery"


class _RunnerNever:
    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
    ) -> ToolRunOutcome:
        raise AssertionError("runner must not be called")
