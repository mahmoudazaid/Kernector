"""Public observability helpers: correlation and safe structured emission."""

from __future__ import annotations

import json
import logging
from contextvars import Token

import pytest

from application import observability
from test.log_record import flatten_log_record, operation_payload, operation_records


@pytest.fixture(autouse=True)
def _reset_request_context() -> None:
    observability.clear_request_id()
    yield
    observability.clear_request_id()


def test_bind_request_id_creates_and_returns_id() -> None:
    assert observability.current_request_id() is None
    bound, token = observability.bind_request_id()
    assert bound
    assert observability.current_request_id() == bound
    assert token is not None
    observability.reset_request_id(token)
    assert observability.current_request_id() is None


def test_bind_request_id_reuses_explicit_id_when_unbound() -> None:
    bound, token = observability.bind_request_id("req-fixed-1")
    assert bound == "req-fixed-1"
    assert observability.current_request_id() == "req-fixed-1"
    observability.reset_request_id(token)


def test_bind_reuses_already_bound_id_by_default() -> None:
    outer, outer_token = observability.bind_request_id("req-outer")
    inner, inner_token = observability.bind_request_id()
    assert inner == outer == "req-outer"
    assert inner_token is None
    observability.reset_request_id(inner_token)
    assert observability.current_request_id() == "req-outer"
    observability.reset_request_id(outer_token)
    assert observability.current_request_id() is None


def test_reset_restores_previous_context_after_exception() -> None:
    outer, outer_token = observability.bind_request_id("req-outer")
    try:
        _inner, inner_token = observability.bind_request_id("req-inner")
        try:
            raise RuntimeError("boom")
        finally:
            observability.reset_request_id(inner_token)
    except RuntimeError:
        pass
    assert observability.current_request_id() == "req-outer"
    observability.reset_request_id(outer_token)


def test_explicit_inner_bind_does_not_clear_outer_on_reset() -> None:
    outer, outer_token = observability.bind_request_id("req-outer")
    inner, inner_token = observability.bind_request_id("req-inner")
    assert inner == "req-inner"
    assert isinstance(inner_token, Token)
    observability.reset_request_id(inner_token)
    assert observability.current_request_id() == "req-outer"
    observability.reset_request_id(outer_token)


def test_log_operation_emits_one_json_object_with_bound_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.success")
    bound, token = observability.bind_request_id("req-turn-9")
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            observability.log_operation(
                logger,
                operation="ask",
                outcome="success",
                latency_ms=12,
                model="test-model",
            )
    finally:
        observability.reset_request_id(token)

    assert len(caplog.records) == 1
    payload = operation_payload(caplog.records[0])
    assert payload == {
        "operation": "ask",
        "outcome": "success",
        "request_id": bound,
        "latency_ms": 12,
        "model": "test-model",
    }
    assert "\n" not in caplog.records[0].getMessage()


def test_log_operation_omits_request_id_when_unbound(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.unbound")

    with caplog.at_level(logging.INFO, logger=logger.name):
        observability.log_operation(
            logger, operation="ingest", outcome="success", chunk_count=3
        )

    payload = operation_payload(caplog.records[0])
    assert payload["operation"] == "ingest"
    assert payload["chunk_count"] == 3
    assert "request_id" not in payload


def test_log_operation_drops_forbidden_field_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.forbid")
    secret = "sk-live-should-never-appear"
    chunk = "CONFIDENTIAL_CHUNK_BODY"

    with caplog.at_level(logging.INFO, logger=logger.name):
        observability.log_operation(
            logger,
            operation="ask",
            outcome="success",
            query="user asked about AUTH-101",
            content=chunk,
            prompt="system prompt leak",
            arguments={"api_key": secret},
            result=chunk,
            message=secret,
            tool="software_delivery.risk_score",
        )

    assert len(caplog.records) == 1
    payload = operation_payload(caplog.records[0])
    flat = flatten_log_record(caplog.records[0])
    assert secret not in flat
    assert chunk not in flat
    assert "user asked about AUTH-101" not in flat
    assert "system prompt leak" not in flat
    assert payload["tool"] == "software_delivery.risk_score"


def test_log_operation_error_uses_error_type_not_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.error")
    leak = "vendor said 401 with sk-abc"

    with caplog.at_level(logging.ERROR, logger=logger.name):
        observability.log_operation(
            logger,
            operation="ask",
            outcome="error",
            level=logging.ERROR,
            error_type="ProviderError",
            message=leak,
        )

    record = caplog.records[0]
    payload = operation_payload(record)
    flat = flatten_log_record(record)
    assert payload["error_type"] == "ProviderError"
    assert leak not in flat
    assert record.exc_info is None


def test_log_operation_multiline_and_forged_values_cannot_split_or_forge_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.inject")
    forged = (
        "legit-model\n"
        "INFO evil operation=forged outcome=success request_id=attacker\r"
        "sk-live-injected"
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        observability.log_operation(
            logger,
            operation="ask",
            outcome="success",
            model=forged,
            path="rag\noperation=forged",
            prompt_key="mode\roperation=hack",
            tool="tool\noperation=evil",
            pack="pack\noperation=evil",
            source_type="knowledge\noperation=evil",
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "\n" not in message
    assert "\r" not in message
    payload = json.loads(message)
    assert payload["operation"] == "ask"
    assert payload["outcome"] == "success"
    assert isinstance(payload["model"], str)
    assert "\n" not in payload["model"]
    assert "\r" not in payload["model"]
    assert operation_records(caplog.records, operation="forged") == []
    assert operation_records(caplog.records, operation="hack") == []
    assert operation_records(caplog.records, operation="evil") == []
