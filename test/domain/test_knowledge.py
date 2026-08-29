"""Unit tests for the knowledge-domain entities."""

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    ScoredChunk,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)

BLANK = ["", "   ", "\n"]


def metadata(source_id: str = "doc-1", **kwargs: object) -> SourceMetadata:
    """A minimal valid SourceMetadata."""
    reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
    return SourceMetadata(reference, **kwargs)


def chunk(source_id: str = "doc-1", index: int = 0) -> DocumentChunk:
    """A minimal valid DocumentChunk."""
    return DocumentChunk(metadata(source_id), index, "chunk text")


def test_ticket_is_not_defined_in_domain_knowledge() -> None:
    import domain.knowledge as knowledge

    assert not hasattr(knowledge, "Ticket")


def test_source_type_has_no_ticket_member() -> None:
    assert not hasattr(SourceType, "TICKET")


def test_valid_source_document_is_accepted() -> None:
    document = SourceDocument(metadata(), "Exploratory testing guidance ...")
    assert document.source_id == "doc-1"
    assert document.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT


def test_source_reference_accepts_opaque_string_source_type() -> None:
    reference = SourceReference("doc-1", "wiki")
    assert reference.source_type == "wiki"


@pytest.mark.parametrize("blank", BLANK)
def test_source_reference_rejects_blank_source_type(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="source_type"):
        SourceReference("doc-1", blank)


@pytest.mark.parametrize("not_a_string", [None, 1, True, ["wiki"], {"kind": "wiki"}])
def test_source_reference_rejects_non_string_source_type(not_a_string: object) -> None:
    with pytest.raises(DomainValidationError, match="source_type"):
        SourceReference("doc-1", not_a_string)  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", BLANK)
def test_source_document_rejects_blank_identifier(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="source_id"):
        SourceDocument(metadata(blank), "content")


@pytest.mark.parametrize("blank", BLANK)
def test_source_document_rejects_blank_content(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="content"):
        SourceDocument(metadata(), blank)


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
    document = SourceDocument(metadata(), "content")
    with pytest.raises(AttributeError):
        document.content = "changed"  # type: ignore[misc]


def test_references_deduplicate_by_value() -> None:
    first = SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    second = SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    assert {first, second} == {first}


@pytest.mark.parametrize("vector", [[0.1, 0.2], (0.1, 0.2), [0, 1], [-0.5]])
def test_embedded_chunk_accepts_any_numeric_sequence(vector: object) -> None:
    embedded = EmbeddedChunk(chunk("doc-9"), vector)  # type: ignore[arg-type]
    assert embedded.vector == vector
    assert embedded.chunk.source_id == "doc-9"


@pytest.mark.parametrize("not_a_sequence", ["0.1,0.2", b"\x00", 0.5, None, {"a": 1}])
def test_embedded_chunk_rejects_non_sequence_vector(not_a_sequence: object) -> None:
    with pytest.raises(DomainValidationError, match="sequence of floats"):
        EmbeddedChunk(chunk(), not_a_sequence)  # type: ignore[arg-type]


def test_embedded_chunk_rejects_empty_vector() -> None:
    with pytest.raises(DomainValidationError, match="non-empty"):
        EmbeddedChunk(chunk(), [])


@pytest.mark.parametrize("vector", [[True], [0.1, "b"], [None], [0.1, [0.2]]])
def test_embedded_chunk_rejects_non_numeric_elements(vector: object) -> None:
    with pytest.raises(DomainValidationError, match="numeric"):
        EmbeddedChunk(chunk(), vector)  # type: ignore[arg-type]


def test_embedded_chunk_rejects_non_chunk() -> None:
    with pytest.raises(DomainValidationError, match="chunk"):
        EmbeddedChunk(metadata(), [0.1])  # type: ignore[arg-type]


@pytest.mark.parametrize("score", [0.87, -0.5, 0, 1, -1.0])
def test_scored_chunk_accepts_the_full_similarity_range(score: object) -> None:
    """Cosine similarity spans [-1, 1]; the port is metric-agnostic, so no clamping."""
    assert ScoredChunk(chunk(), score).score == score  # type: ignore[arg-type]


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_scored_chunk_rejects_non_finite_score(score: float) -> None:
    with pytest.raises(DomainValidationError, match="finite"):
        ScoredChunk(chunk(), score)


@pytest.mark.parametrize("score", [True, "0.5", None, [0.5]])
def test_scored_chunk_rejects_non_numeric_score(score: object) -> None:
    with pytest.raises(DomainValidationError, match="score"):
        ScoredChunk(chunk(), score)  # type: ignore[arg-type]


def test_scored_chunk_rejects_non_chunk() -> None:
    with pytest.raises(DomainValidationError, match="chunk"):
        ScoredChunk(metadata(), 0.5)  # type: ignore[arg-type]


def test_retrieval_entities_are_immutable() -> None:
    embedded = EmbeddedChunk(chunk(), [0.1])
    scored = ScoredChunk(chunk(), 0.5)
    with pytest.raises(AttributeError):
        embedded.vector = [0.2]  # type: ignore[misc]
    with pytest.raises(AttributeError):
        scored.score = 0.9  # type: ignore[misc]
