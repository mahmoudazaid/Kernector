"""Unit tests for application-layer document chunking."""

import pytest

from application.chunking import chunk_document
from application.errors import ApplicationValidationError
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)


def _document(
    content: str,
    *,
    source_id: str = "doc-1",
    **metadata_kwargs: object,
) -> SourceDocument:
    reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
    return SourceDocument(SourceMetadata(reference, **metadata_kwargs), content)


def test_short_content_produces_single_chunk() -> None:
    document = _document("hello")
    chunks = chunk_document(document, chunk_size=10, chunk_overlap=2)

    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].content == "hello"


def test_content_equal_to_chunk_size_produces_single_chunk() -> None:
    document = _document("12345")
    chunks = chunk_document(document, chunk_size=5, chunk_overlap=1)

    assert len(chunks) == 1
    assert chunks[0].content == "12345"


def test_long_content_produces_overlapping_indexed_chunks() -> None:
    document = _document("abcdefghij")  # 10 chars
    chunks = chunk_document(document, chunk_size=5, chunk_overlap=2)

    assert [c.index for c in chunks] == [0, 1, 2]
    assert [c.content for c in chunks] == ["abcde", "defgh", "ghij"]
    assert all(len(c.content) <= 5 for c in chunks)
    assert chunks[0].content[-2:] == chunks[1].content[:2]
    assert chunks[1].content[-2:] == chunks[2].content[:2]


def test_reconstruction_without_overlap_matches_original() -> None:
    text = "abcdefghij"
    document = _document(text)
    chunk_size, overlap = 5, 2
    chunks = chunk_document(document, chunk_size=chunk_size, chunk_overlap=overlap)

    rebuilt = chunks[0].content
    for chunk in chunks[1:]:
        rebuilt += chunk.content[overlap:]
    assert rebuilt == text


def test_metadata_object_and_provenance_are_preserved() -> None:
    document = _document("abcdefghij", title="Demo")
    chunks = chunk_document(document, chunk_size=5, chunk_overlap=2)

    assert all(chunk.metadata is document.metadata for chunk in chunks)
    assert all(chunk.source_id == document.source_id for chunk in chunks)
    assert all(chunk.reference == document.reference for chunk in chunks)


def test_story_specific_metadata_is_not_required() -> None:
    document = _document("short text")  # no extra/doc_type/tags
    chunks = chunk_document(document, chunk_size=50, chunk_overlap=0)
    assert len(chunks) == 1


def test_arbitrary_extra_metadata_is_left_opaque() -> None:
    document = _document(
        "abcdefghij",
        extra={"provider_field": "whatever", "tags_json": '["a"]'},
    )
    chunks = chunk_document(document, chunk_size=5, chunk_overlap=2)
    assert all(chunk.metadata.extra == document.metadata.extra for chunk in chunks)


def test_rejects_non_source_document() -> None:
    with pytest.raises(ApplicationValidationError, match="SourceDocument"):
        chunk_document("not a document", chunk_size=5, chunk_overlap=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [
        (0, 0),
        (-1, 0),
        (5, -1),
        (5, 5),
        (5, 6),
        (True, 0),
        (5, False),
        (5.0, 1),
        (5, "1"),
    ],
)
def test_rejects_invalid_settings(
    chunk_size: object, chunk_overlap: object
) -> None:
    document = _document("hello world")
    with pytest.raises(ApplicationValidationError):
        chunk_document(
            document,
            chunk_size=chunk_size,  # type: ignore[arg-type]
            chunk_overlap=chunk_overlap,  # type: ignore[arg-type]
        )