"""MCP search_knowledge identifiers / project_id / contexts schema (#373)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp.search_knowledge import (
    MAX_IDENTIFIERS,
    MAX_IDENTIFIER_CHARS,
    SearchKnowledgeArgs,
    SearchKnowledgeTool,
)
from domain.errors import ToolArgumentValidationError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)


class _CaptureRetrieve:
    def __init__(self) -> None:
        self.last: RetrieveRequest | None = None

    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        self.last = request
        chunk = DocumentChunk(
            metadata=SourceMetadata(
                SourceReference("cloud/PROJ:PROJ-123", SourceType.JIRA),
                title="story",
            ),
            index=0,
            content="Cancel unpaid order",
        )
        return RetrieveResponse(hits=(ScoredChunk(chunk=chunk, score=1.0),))


def test_query_only_compatibility() -> None:
    args = SearchKnowledgeArgs.model_validate(
        {"query": "restart service", "retrieval_limit": 3}
    )
    assert args.query == "restart service"
    assert args.identifiers == []
    assert args.project_id is None


def test_identifier_only_request() -> None:
    args = SearchKnowledgeArgs.model_validate(
        {"identifiers": ["PROJ-123"], "project_id": "prj_proj"}
    )
    assert args.query == ""
    assert args.identifiers == ["PROJ-123"]


def test_mixed_query_and_identifiers() -> None:
    args = SearchKnowledgeArgs.model_validate(
        {
            "query": "cancel rules",
            "identifiers": ["PROJ-123"],
            "project_id": "prj_proj",
            "contexts": ["business"],
        }
    )
    assert args.query == "cancel rules"
    assert args.identifiers == ["PROJ-123"]
    assert args.contexts == ["business"]


def test_identifiers_are_bounded() -> None:
    with pytest.raises(ValidationError):
        SearchKnowledgeArgs.model_validate(
            {"identifiers": ["x" * (MAX_IDENTIFIER_CHARS + 1)]}
        )
    with pytest.raises(ValidationError):
        SearchKnowledgeArgs.model_validate(
            {"identifiers": [f"k{i}" for i in range(MAX_IDENTIFIERS + 1)]}
        )


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        SearchKnowledgeArgs.model_validate(
            {"query": "q", "unexpected": True}
        )


def test_tool_forwards_identifiers_and_project() -> None:
    retrieve = _CaptureRetrieve()
    tool = SearchKnowledgeTool(retrieve)  # type: ignore[arg-type]

    raw = tool.run(
        {
            "query": "cancel",
            "identifiers": ["PROJ-123"],
            "project_id": "prj_proj",
            "contexts": ["business"],
        }
    )
    payload = json.loads(raw)

    assert retrieve.last is not None
    assert retrieve.last.identifiers == ("PROJ-123",)
    assert retrieve.last.project_id == "prj_proj"
    assert retrieve.last.contexts == ("business",)
    assert payload["evidence"][0]["source"]["source_id"] == "cloud/PROJ:PROJ-123"


def test_tool_rejects_neither_query_nor_identifiers() -> None:
    tool = SearchKnowledgeTool(_CaptureRetrieve())  # type: ignore[arg-type]
    with pytest.raises(ToolArgumentValidationError):
        tool.run({})
