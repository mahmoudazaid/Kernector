"""Filter-then-limit contract for the InMemoryVectorStore double."""

from domain.knowledge import (
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
