"""Public observability helpers: correlation and safe structured emission."""

from __future__ import annotations

import logging

import pytest

from application import observability
from test.log_record import flatten_log_record


@pytest.fixture(autouse=True)
def _clear_request_id() -> None:
    observability.clear_request_id()
    yield
    observability.clear_request_id()


def test_bind_request_id_creates_and_returns_id() -> None:
    assert observability.current_request_id() is None
    bound = observability.bind_request_id()
    assert bound
    assert observability.current_request_id() == bound


def test_bind_request_id_reuses_explicit_id() -> None:
    bound = observability.bind_request_id("req-fixed-1")
    assert bound == "req-fixed-1"
    assert observability.current_request_id() == "req-fixed-1"


def test_clear_request_id_resets_context() -> None:
    observability.bind_request_id("req-temp")
    observability.clear_request_id()
    assert observability.current_request_id() is None


def test_log_operation_includes_bound_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.success")
    observability.bind_request_id("req-turn-9")

    with caplog.at_level(logging.INFO, logger=logger.name):
        observability.log_operation(
            logger,
            operation="ask",
            outcome="success",
            latency_ms=12,
            model="test-model",
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "operation=ask" in message
    assert "outcome=success" in message
    assert "request_id=req-turn-9" in message
    assert "latency_ms=12" in message
    assert "model=test-model" in message


def test_log_operation_omits_request_id_when_unbound(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.observability.unbound")

    with caplog.at_level(logging.INFO, logger=logger.name):
        observability.log_operation(
            logger, operation="ingest", outcome="success", chunk_count=3
        )

    message = caplog.records[0].getMessage()
    assert "operation=ingest" in message
    assert "chunk_count=3" in message
    assert "request_id=" not in message


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
    flat = flatten_log_record(caplog.records[0])
    assert secret not in flat
    assert chunk not in flat
    assert "user asked about AUTH-101" not in flat
    assert "system prompt leak" not in flat
    assert "tool=software_delivery.risk_score" in flat


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
    flat = flatten_log_record(record)
    assert "error_type=ProviderError" in record.getMessage()
    assert leak not in flat
    assert record.exc_info is None
