"""Tests for test-design model JSON extraction."""

from __future__ import annotations

import pytest

from domain.errors import ToolFailureError
from packs.software_delivery.test_design.model_json import loads_model_json_object


def test_loads_raw_json_object() -> None:
    data = loads_model_json_object(
        '{"candidates":[]}',
        failure_prefix="Coverage planning result",
    )
    assert data == {"candidates": []}


def test_loads_fenced_json_object() -> None:
    data = loads_model_json_object(
        '```json\n{"candidates":[{"candidate_id":"c1"}]}\n```',
        failure_prefix="Coverage planning result",
    )
    assert data["candidates"] == [{"candidate_id": "c1"}]


def test_rejects_truncated_json() -> None:
    with pytest.raises(ToolFailureError, match="not valid JSON"):
        loads_model_json_object(
            '{"candidates":[{"title":"unterminated',
            failure_prefix="Coverage planning result",
        )


def test_rejects_non_object_json() -> None:
    with pytest.raises(ToolFailureError, match="JSON object"):
        loads_model_json_object("[]", failure_prefix="Coverage planning result")
