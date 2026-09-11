"""Filter-then-limit contract for the InMemoryVectorStore double."""

from domain.knowledge import (
    ChunkPage,
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.doubles import InMemoryVectorStore, vector_for

PROBE = vector_for("probe")


def _chunk(
    source_id: str,
    *,
    extra: dict[str, str] | None = None,
    content: str = "body",
    index: int = 0,
) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            extra=extra or {},
        ),
        index=index,
        content=content,
    )


def _seed(store: InMemoryVectorStore, *chunks: DocumentChunk) -> None:
    store.upsert(
        [
            EmbeddedChunk(chunk=chunk, vector=vector_for(chunk.content))
            for chunk in chunks
        ]
    )


def test_unfiltered_search_returns_insertion_order_up_to_limit() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("a"), _chunk("b"), _chunk("c"))

    hits = store.search(PROBE, 2)

    assert [hit.chunk.source_id for hit in hits] == ["a", "b"]


def test_empty_and_none_filters_match_unfiltered_path() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("a"), _chunk("b"))

    assert [hit.chunk.source_id for hit in store.search(PROBE, 10)] == ["a", "b"]
    assert [
        hit.chunk.source_id
        for hit in store.search(PROBE, 10, metadata_filters=None)
    ] == ["a", "b"]
    assert [
        hit.chunk.source_id for hit in store.search(PROBE, 10, metadata_filters={})
    ] == ["a", "b"]


def test_single_extra_filter_keeps_exact_matches_only() -> None:
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("runbook", extra={"doc_type": "runbook"}),
        _chunk("policy", extra={"doc_type": "policy"}),
        _chunk("missing"),
    )

    hits = store.search(PROBE, 10, metadata_filters={"doc_type": "runbook"})

    assert [hit.chunk.source_id for hit in hits] == ["runbook"]
    assert dict(hits[0].chunk.metadata.extra) == {"doc_type": "runbook"}


def test_and_filters_require_every_key_to_match() -> None:
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("both", extra={"doc_type": "runbook", "severity": "high"}),
        _chunk("type_only", extra={"doc_type": "runbook", "severity": "low"}),
        _chunk("sev_only", extra={"doc_type": "policy", "severity": "high"}),
        _chunk("missing_sev", extra={"doc_type": "runbook"}),
    )

    hits = store.search(
        PROBE,
        10,
        metadata_filters={"doc_type": "runbook", "severity": "high"},
    )

    assert [hit.chunk.source_id for hit in hits] == ["both"]


def test_missing_filter_key_excludes_chunk() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("no-extra"), _chunk("other", extra={"severity": "high"}))

    hits = store.search(PROBE, 10, metadata_filters={"doc_type": "runbook"})

    assert hits == ()


def test_filters_apply_before_limit() -> None:
    """Nearest-by-insertion non-match must not consume the limit budget."""
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("nearest-non-match", extra={"doc_type": "policy"}),
        _chunk("match-a", extra={"doc_type": "runbook"}),
        _chunk("match-b", extra={"doc_type": "runbook"}),
    )

    hits = store.search(PROBE, 1, metadata_filters={"doc_type": "runbook"})

    assert [hit.chunk.source_id for hit in hits] == ["match-a"]


def test_owned_scalar_fields_are_not_filter_targets() -> None:
    """Filters address SourceMetadata.extra only, not adapter-owned scalars."""
    store = InMemoryVectorStore()
    _seed(
        store,
        DocumentChunk(
            metadata=SourceMetadata(
                SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT),
                title="runbook",
                extra={},
            ),
            index=0,
            content="body",
        ),
        _chunk("real", extra={"title": "runbook"}),
    )

    hits = store.search(PROBE, 10, metadata_filters={"title": "runbook"})

    assert [hit.chunk.source_id for hit in hits] == ["real"]


def test_list_source_chunks_isolates_same_source_id_under_different_types() -> None:
    store = InMemoryVectorStore()
    kd = DocumentChunk(
        metadata=SourceMetadata(
            SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT),
            title="KD",
            extra={"kind": "kd"},
        ),
        index=0,
        content="knowledge body",
    )
    gd = DocumentChunk(
        metadata=SourceMetadata(
            SourceReference("doc-1", SourceType.GOOGLE_DRIVE),
            title="GD",
            provider="google",
            extra={"kind": "gd"},
        ),
        index=0,
        content="drive body",
    )
    _seed(store, kd, gd)

    listed = store.list_source_chunks(
        SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    )

    assert len(listed.chunks) == 1
    assert listed.chunks[0].content == "knowledge body"
    assert listed.chunks[0].metadata.title == "KD"
    assert listed.chunks[0].reference.source_type == SourceType.KNOWLEDGE_DOCUMENT
    assert listed.has_more is False


def test_list_source_chunks_returns_deterministic_index_order_with_provenance() -> None:
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk(
            metadata=SourceMetadata(
                SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT),
                title="Report",
                provider="upload",
                content_format="text/plain",
                extra={"page": "2"},
            ),
            index=2,
            content="third",
        ),
        DocumentChunk(
            metadata=SourceMetadata(
                SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT),
                title="Report",
                provider="upload",
                content_format="text/plain",
                extra={"page": "0"},
            ),
            index=0,
            content="first",
        ),
        DocumentChunk(
            metadata=SourceMetadata(
                SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT),
                title="Report",
                provider="upload",
                content_format="text/plain",
                extra={"page": "1"},
            ),
            index=1,
            content="second",
        ),
    ]
    _seed(store, *chunks)

    listed = store.list_source_chunks(
        SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    )

    assert [c.index for c in listed.chunks] == [0, 1, 2]
    assert [c.content for c in listed.chunks] == ["first", "second", "third"]
    assert listed.chunks[0].metadata.title == "Report"
    assert listed.chunks[0].metadata.provider == "upload"
    assert listed.chunks[0].metadata.content_format == "text/plain"
    assert dict(listed.chunks[1].metadata.extra) == {"page": "1"}


def test_list_source_chunks_missing_reference_returns_empty() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("other"))

    listed = store.list_source_chunks(
        SourceReference("missing", SourceType.KNOWLEDGE_DOCUMENT)
    )

    assert listed == ChunkPage(chunks=(), has_more=False)


def test_list_source_chunks_applies_limit_and_offset() -> None:
    store = InMemoryVectorStore()
    reference = SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT)
    for index in range(5):
        _seed(store, _chunk("doc-1", index=index, content=f"c{index}"))

    page = store.list_source_chunks(reference, limit=2, offset=1)

    assert [c.content for c in page.chunks] == ["c1", "c2"]
    assert page.has_more is True
