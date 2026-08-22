"""Unit tests for the knowledge-domain entities."""

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import (
    DocumentChunk,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
    Ticket,
)

BLANK = ["", "   ", "\n"]


def metadata(source_id: str = "doc-1", **kwargs: object) -> SourceMetadata:
    """A minimal valid SourceMetadata."""
    reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
    return SourceMetadata(reference, **kwargs)


def test_valid_ticket_is_accepted() -> None:
    ticket = Ticket("KRN-1", "As a QA analyst I want ...", title="Login")
    assert ticket.reference == SourceReference("KRN-1", SourceType.TICKET)


def test_valid_source_document_is_accepted() -> None:
    document = SourceDocument(metadata(), "Exploratory testing guidance ...")
    assert document.source_id == "doc-1"
    assert document.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT


@pytest.mark.parametrize("blank", BLANK)
def test_ticket_rejects_blank_identifier(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="ticket_id"):
        Ticket(blank, "content")


@pytest.mark.parametrize("blank", BLANK)
def test_source_document_rejects_blank_identifier(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="source_id"):
        SourceDocument(metadata(blank), "content")


@pytest.mark.parametrize("blank", BLANK)
def test_ticket_rejects_blank_content(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="content"):
        Ticket("KRN-1", blank)


@pytest.mark.parametrize("blank", BLANK)
def test_source_document_rejects_blank_content(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="content"):
        SourceDocument(metadata(), blank)


def test_none_identifier_raises_domain_error() -> None:
    with pytest.raises(DomainValidationError):
        Ticket(None, "content")  # type: ignore[arg-type]


def test_source_reference_rejects_raw_string_source_type() -> None:
    with pytest.raises(DomainValidationError, match="source_type"):
        SourceReference("doc-1", "ticket")  # type: ignore[arg-type]


def test_unsupported_source_type_is_not_constructible() -> None:
    with pytest.raises(ValueError):
        SourceType("email")


def test_metadata_rejects_non_reference() -> None:
    with pytest.raises(DomainValidationError, match="reference"):
        SourceMetadata("doc-1")  # type: ignore[arg-type]


def test_metadata_preserves_source_identifier() -> None:
    meta = metadata("doc-42", provider="GITHUB", content_format="markdown")
    assert meta.source_id == "doc-42"
    assert meta.provider == "GITHUB"
    assert meta.extra == {}


def test_valid_chunk_preserves_source_identifier_and_index() -> None:
    chunk = DocumentChunk(metadata("doc-7"), 3, "chunk text")
    assert chunk.source_id == "doc-7"
    assert chunk.index == 3
    assert chunk.reference == SourceReference(
        "doc-7", SourceType.KNOWLEDGE_DOCUMENT
    )


def test_chunk_accepts_zero_index() -> None:
    assert DocumentChunk(metadata(), 0, "chunk text").index == 0


@pytest.mark.parametrize("blank", BLANK)
def test_chunk_rejects_blank_content(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="content"):
        DocumentChunk(metadata(), 0, blank)


def test_chunk_rejects_missing_source_reference() -> None:
    with pytest.raises(DomainValidationError, match="metadata"):
        DocumentChunk(None, 0, "chunk text")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_index", [-1, True, "0", 1.5, None])
def test_chunk_rejects_invalid_index(bad_index: object) -> None:
    with pytest.raises(DomainValidationError, match="index"):
        DocumentChunk(metadata(), bad_index, "chunk text")  # type: ignore[arg-type]


def test_entities_are_immutable() -> None:
    ticket = Ticket("KRN-1", "content")
    with pytest.raises(AttributeError):
        ticket.content = "changed"  # type: ignore[misc]


def test_references_deduplicate_by_value() -> None:
    first = SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    second = SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    assert {first, second} == {first}
