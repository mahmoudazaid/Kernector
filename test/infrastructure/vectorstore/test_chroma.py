"""Chroma adapter behavior: identity, metadata, writes, search, and failures."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import (
    ChromaStoreError,
    ChromaVectorStore,
    _derive_id,
)

COLLECTION = "kernector_knowledge"
ALIGNED = (1.0, 0.0, 0.0)
ORTHOGONAL = (0.0, 1.0, 0.0)
OPPOSING = (-1.0, 0.0, 0.0)


def settings(path: Path, collection: str = COLLECTION) -> ChromaSettings:
    """Build settings directly, never through `load_settings()`.

    `load_settings()` calls `load_dotenv(override=True)`, so a developer's local
    `.env` would beat anything the test sets and the store could land in their
    real data directory (§3.1).
    """
    return ChromaSettings(persist_path=path, collection=collection)


def make_chunk(
    source_id: str = "doc-1",
    index: int = 0,
    content: str = "body",
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
    **metadata_fields: object,
) -> DocumentChunk:
    metadata = SourceMetadata(
        reference=SourceReference(source_id, source_type), **metadata_fields
    )
    return DocumentChunk(metadata=metadata, index=index, content=content)


def make_embedded(
    vector: tuple[float, ...] = ALIGNED, **chunk_fields: object
) -> EmbeddedChunk:
    return EmbeddedChunk(chunk=make_chunk(**chunk_fields), vector=list(vector))


def count(store: ChromaVectorStore) -> int:
    """Record count read through the public surface."""
    return len(store.search(ALIGNED, 1000))


def _raw_by_id(
    store: ChromaVectorStore, *, ids: list[str] | None = None
) -> dict[str, tuple[tuple[float, ...], str, dict[str, object]]]:
    """Order-independent raw Chroma rows keyed by record id."""
    kwargs: dict[str, object] = {
        "include": ["metadatas", "documents", "embeddings"],
    }
    if ids is not None:
        kwargs["ids"] = ids
    result = store._collection.get(**kwargs)
    found = list(result.get("ids") or [])
    documents = list(result.get("documents") or [])
    metadatas = list(result.get("metadatas") or [])
    embeddings_raw = result.get("embeddings")
    if embeddings_raw is None:
        embeddings: list[object] = []
    else:
        embeddings = list(embeddings_raw)
    rows: dict[str, tuple[tuple[float, ...], str, dict[str, object]]] = {}
    for record_id, document, metadata, embedding in zip(
        found, documents, metadatas, embeddings, strict=True
    ):
        rows[str(record_id)] = (
            tuple(float(v) for v in embedding),  # type: ignore[arg-type]
            str(document),
            dict(metadata or {}),
        )
    return rows


def round_trip(store: ChromaVectorStore, chunk: DocumentChunk) -> DocumentChunk:
    """Persist a chunk and read it back, exercising encode and decode together."""
    store.upsert([EmbeddedChunk(chunk=chunk, vector=list(ALIGNED))])
    results = store.search(ALIGNED, 1)
    assert len(results) == 1
    return results[0].chunk


@pytest.fixture
def store(tmp_path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(settings(tmp_path / "chroma"))


# --------------------------------------------------------------------------
# Identity (§5)
# --------------------------------------------------------------------------


def test_same_identity_upserts_in_place(store: ChromaVectorStore) -> None:
    store.upsert([make_embedded()])
    store.upsert([make_embedded()])
    assert count(store) == 1


def test_different_index_is_a_different_record(store: ChromaVectorStore) -> None:
    store.upsert([make_embedded(index=0), make_embedded(index=1)])
    assert count(store) == 2


@pytest.mark.parametrize("source_id", ["a:b|c", "مستند-١", "with spaces", "-"])
def test_unusual_source_ids_persist_and_stay_distinct(
    store: ChromaVectorStore, source_id: str
) -> None:
    """Delimiters and Unicode in the source id must not collide or corrupt."""
    store.upsert([make_embedded(source_id=source_id), make_embedded(source_id="plain")])
    assert count(store) == 2
    ids = {r.chunk.metadata.reference.source_id for r in store.search(ALIGNED, 10)}
    assert ids == {source_id, "plain"}


def test_duplicate_derived_ids_in_one_batch_are_rejected(
    store: ChromaVectorStore,
) -> None:
    with pytest.raises(ChromaStoreError, match="same record ID"):
        store.upsert([make_embedded(), make_embedded()])
    assert count(store) == 0


# --------------------------------------------------------------------------
# Metadata (§6, §6.1)
# --------------------------------------------------------------------------


def test_complete_optional_fields_round_trip(store: ChromaVectorStore) -> None:
    original = make_chunk(
        title="A title",
        provider="jira",
        content_format="markdown",
        extra={"team": "core"},
    )
    assert round_trip(store, original) == original


def test_absent_optional_fields_round_trip_as_none(store: ChromaVectorStore) -> None:
    decoded = round_trip(store, make_chunk())
    assert decoded.metadata.title is None
    assert decoded.metadata.provider is None
    assert decoded.metadata.content_format is None


def test_empty_extra_round_trips(store: ChromaVectorStore) -> None:
    assert dict(round_trip(store, make_chunk(extra={})).metadata.extra) == {}


def test_json_document_value_round_trips_byte_for_byte(
    store: ChromaVectorStore,
) -> None:
    """A string that is itself JSON must survive intact, not be re-parsed."""
    nested = '{"a": [1, 2], "b": null}'
    decoded = round_trip(store, make_chunk(extra={"tags_json": nested}))
    assert decoded.metadata.extra["tags_json"] == nested


def test_unicode_delimiter_and_empty_keys_round_trip(
    store: ChromaVectorStore,
) -> None:
    extra = {"ünï:code": "قيمة", "a.b|c": "delimited", "": "empty key", "z": ""}
    decoded = round_trip(store, make_chunk(extra=extra))
    assert dict(decoded.metadata.extra) == extra


def test_extra_keys_colliding_with_reserved_names_do_not_shadow_them(
    store: ChromaVectorStore,
) -> None:
    """Caller keys live in the JSON envelope, never in Chroma's scalar space."""
    extra = {"title": "fake", "source_id": "fake", "chunk_index": "fake"}
    decoded = round_trip(store, make_chunk(title="real", extra=extra))
    assert decoded.metadata.title == "real"
    assert decoded.metadata.reference.source_id == "doc-1"
    assert decoded.index == 0
    assert dict(decoded.metadata.extra) == extra


def test_non_json_serializable_extra_value_is_rejected(
    store: ChromaVectorStore,
) -> None:
    """`extra` is annotated Mapping[str, str] and `__post_init__` does not
    enforce it, so this deliberately violates the annotation to prove the
    adapter's defensive guard fires instead of silently calling str() (§6.1).
    """
    with pytest.raises(ChromaStoreError, match="not JSON-serializable"):
        store.upsert([make_embedded(extra={"bad": object()})])


# --------------------------------------------------------------------------
# Writes (§8)
# --------------------------------------------------------------------------


def test_empty_input_is_a_no_op(store: ChromaVectorStore) -> None:
    store.upsert([])
    assert count(store) == 0


def test_single_and_batch_writes(store: ChromaVectorStore) -> None:
    store.upsert([make_embedded(index=0)])
    assert count(store) == 1
    store.upsert([make_embedded(index=1), make_embedded(index=2)])
    assert count(store) == 3


def test_re_adding_replaces_content_vector_and_metadata(
    store: ChromaVectorStore,
) -> None:
    store.upsert([make_embedded(content="before", title="old")])
    store.upsert([make_embedded(vector=ORTHOGONAL, content="after", title="new")])
    assert count(store) == 1
    updated = store.search(ORTHOGONAL, 1)[0]
    assert updated.chunk.content == "after"
    assert updated.chunk.metadata.title == "new"
    assert updated.score == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_vector_values_are_rejected(
    store: ChromaVectorStore, bad: float
) -> None:
    """`EmbeddedChunk` accepts these; rejecting them is the adapter's job."""
    with pytest.raises(ChromaStoreError, match="finite"):
        store.upsert([make_embedded(vector=(bad, 0.0, 0.0))])
    assert count(store) == 0


def test_mixed_dimensions_in_one_batch_are_rejected(
    store: ChromaVectorStore,
) -> None:
    with pytest.raises(ChromaStoreError, match="dimension"):
        store.upsert(
            [make_embedded(index=0), make_embedded(index=1, vector=(1.0, 0.0))]
        )
    assert count(store) == 0


def test_dimension_mismatch_against_the_collection_is_rejected(
    store: ChromaVectorStore,
) -> None:
    store.upsert([make_embedded()])
    with pytest.raises(ChromaStoreError):
        store.upsert([make_embedded(index=1, vector=(1.0, 0.0))])


def test_non_embedded_chunk_items_are_rejected(store: ChromaVectorStore) -> None:
    with pytest.raises(ChromaStoreError, match="EmbeddedChunk"):
        store.upsert(["not a chunk"])
    assert count(store) == 0


# --------------------------------------------------------------------------
# Source deletion (§5.1)
# --------------------------------------------------------------------------


def make_reference(
    source_id: str = "doc-1",
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
) -> SourceReference:
    return SourceReference(source_id, source_type)


def stored_identities(store: ChromaVectorStore) -> list[tuple[str, str, int]]:
    """Every record's identity, read back through the public surface."""
    return sorted(
        (
            str(scored.chunk.reference.source_type),
            scored.chunk.reference.source_id,
            scored.chunk.index,
        )
        for scored in store.search(ALIGNED, 1000)
    )


def test_delete_source_removes_every_chunk_of_that_source(
    store: ChromaVectorStore,
) -> None:
    store.upsert(
        [
            make_embedded(source_id="doc-1", index=0),
            make_embedded(source_id="doc-1", index=1),
            make_embedded(source_id="doc-1", index=2),
        ]
    )
    assert count(store) == 3

    store.delete_source(make_reference("doc-1"))

    assert count(store) == 0


def test_delete_source_preserves_other_sources(store: ChromaVectorStore) -> None:
    store.upsert(
        [
            make_embedded(source_id="doc-1", index=0),
            make_embedded(source_id="doc-1", index=1),
            make_embedded(source_id="doc-2", index=0),
        ]
    )

    store.delete_source(make_reference("doc-1"))

    assert stored_identities(store) == [("knowledge_document", "doc-2", 0)]


def test_different_source_type_is_a_different_record(store: ChromaVectorStore) -> None:
    store.upsert(
        [
            make_embedded(source_id="shared", source_type="knowledge_document"),
            make_embedded(source_id="shared", source_type="connector_feed"),
        ]
    )

    assert stored_identities(store) == [
        ("connector_feed", "shared", 0),
        ("knowledge_document", "shared", 0),
    ]


def test_delete_source_preserves_the_same_id_under_another_source_type(
    store: ChromaVectorStore,
) -> None:
    store.upsert(
        [
            make_embedded(source_id="shared", source_type="knowledge_document"),
            make_embedded(source_id="shared", source_type="connector_feed"),
        ]
    )

    store.delete_source(make_reference("shared", source_type="knowledge_document"))

    assert stored_identities(store) == [("connector_feed", "shared", 0)]


def test_deleting_an_unknown_source_is_a_no_op(store: ChromaVectorStore) -> None:
    store.upsert([make_embedded(source_id="doc-1", index=0)])

    store.delete_source(make_reference("never-stored"))

    assert stored_identities(store) == [("knowledge_document", "doc-1", 0)]


def test_deleting_from_an_empty_collection_is_a_no_op(
    store: ChromaVectorStore,
) -> None:
    """A zero-match `where` deletes nothing; only a filterless delete errors."""
    store.delete_source(make_reference("doc-1"))

    assert count(store) == 0


@pytest.mark.parametrize(
    "source_id",
    ["doc:1#0", "  spaced  ", "документ", "文档-1", "emoji-🙂", '{"json":"like"}'],
)
def test_delete_source_handles_unusual_identifiers(
    tmp_path: Path, source_id: str
) -> None:
    """Delimiters, whitespace, and non-ASCII must still scope correctly.

    A fresh store per case, so one identifier cannot mask another.
    """
    store = ChromaVectorStore(settings(tmp_path / "chroma"))
    store.upsert(
        [
            make_embedded(source_id=source_id, index=0),
            make_embedded(source_id=source_id, index=1),
            make_embedded(source_id="other", index=0),
        ]
    )

    store.delete_source(make_reference(source_id))

    assert stored_identities(store) == [("knowledge_document", "other", 0)]


def test_deletion_persists_after_reopening_the_store(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    first = ChromaVectorStore(settings(path))
    first.upsert(
        [
            make_embedded(source_id="doc-1", index=0),
            make_embedded(source_id="doc-2", index=0),
        ]
    )
    first.delete_source(make_reference("doc-1"))

    reopened = ChromaVectorStore(settings(path))

    assert stored_identities(reopened) == [("knowledge_document", "doc-2", 0)]


@pytest.mark.parametrize("bad", ["doc-1", None, 42, ("doc-1", "knowledge_document")])
def test_delete_source_rejects_a_non_reference(
    store: ChromaVectorStore, bad: object
) -> None:
    with pytest.raises(ChromaStoreError, match="reference"):
        store.delete_source(bad)


def test_a_delete_failure_stays_a_store_error(tmp_path: Path) -> None:
    """Adapter failures keep the store error type, never a configuration error.

    The collection is dropped from under the adapter, which is the cheapest
    real vendor failure available; nothing here is mocked.
    """
    store = ChromaVectorStore(settings(tmp_path / "chroma"))
    store.upsert([make_embedded(source_id="doc-1", index=0)])
    store._client.delete_collection(COLLECTION)

    with pytest.raises(ChromaStoreError, match="could not delete source"):
        store.delete_source(make_reference("doc-1"))


# --------------------------------------------------------------------------
# Search (§9)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def populated(tmp_path_factory: pytest.TempPathFactory) -> ChromaVectorStore:
    """One store shared by the read-only search cases.

    Module-scoped so the HNSW index is built once rather than per test. That
    forces `tmp_path_factory`: `tmp_path` is function-scoped and cannot be
    requested from a broader scope (§11).
    """
    path = tmp_path_factory.mktemp("populated") / "chroma"
    shared = ChromaVectorStore(settings(path))
    shared.upsert(
        [
            make_embedded(vector=ALIGNED, index=0, content="aligned"),
            make_embedded(vector=ORTHOGONAL, index=1, content="orthogonal"),
            make_embedded(vector=OPPOSING, index=2, content="opposing"),
        ]
    )
    return shared


def test_search_on_an_empty_collection_returns_empty(
    store: ChromaVectorStore,
) -> None:
    assert store.search(ALIGNED, 5) == ()


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_non_positive_limit_returns_empty(
    populated: ChromaVectorStore, limit: int
) -> None:
    assert populated.search(ALIGNED, limit) == ()


@pytest.mark.parametrize("limit", [True, False, 2.0, "2", None])
def test_non_integer_limit_is_rejected(
    populated: ChromaVectorStore, limit: object
) -> None:
    """`False` must be rejected, not fall through to the `limit <= 0` rule."""
    with pytest.raises(ChromaStoreError, match="limit must be an int"):
        populated.search(ALIGNED, limit)


def test_top_k_limits_the_result_count(populated: ChromaVectorStore) -> None:
    assert len(populated.search(ALIGNED, 2)) == 2


def test_limit_larger_than_the_collection_returns_everything(
    populated: ChromaVectorStore,
) -> None:
    """chromadb 1.5.9 returns fewer results than asked without error."""
    assert len(populated.search(ALIGNED, 50)) == 3


def test_results_are_ordered_nearest_first(populated: ChromaVectorStore) -> None:
    results = populated.search(ALIGNED, 3)
    assert [r.chunk.content for r in results] == [
        "aligned",
        "orthogonal",
        "opposing",
    ]
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_identical_vector_scores_approximately_one(
    populated: ChromaVectorStore,
) -> None:
    assert populated.search(ALIGNED, 1)[0].score == pytest.approx(1.0, abs=1e-6)


def test_opposing_vector_yields_an_unclamped_negative_score(
    populated: ChromaVectorStore,
) -> None:
    worst = populated.search(ALIGNED, 3)[-1]
    assert worst.chunk.content == "opposing"
    assert worst.score == pytest.approx(-1.0, abs=1e-6)


def test_search_reconstructs_full_domain_objects(
    populated: ChromaVectorStore,
) -> None:
    top = populated.search(ALIGNED, 1)[0]
    assert isinstance(top.chunk, DocumentChunk)
    assert isinstance(top.chunk.metadata.reference.source_type, str)
    assert top.chunk.metadata.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT
    assert top.chunk.index == 0


@pytest.mark.parametrize(
    "vector",
    [(), (True, 0.0, 0.0), (float("nan"), 0.0, 0.0), (float("inf"), 0.0, 0.0), "abc"],
)
def test_invalid_query_vectors_are_rejected(
    populated: ChromaVectorStore, vector: object
) -> None:
    with pytest.raises(ChromaStoreError):
        populated.search(vector, 3)


def test_query_dimension_mismatch_is_rejected(
    populated: ChromaVectorStore,
) -> None:
    with pytest.raises(ChromaStoreError, match="could not query"):
        populated.search((1.0, 0.0), 3)


# --------------------------------------------------------------------------
# Metadata-filtered search (#86)
# --------------------------------------------------------------------------


def test_single_extra_filter_returns_exact_matches_only(
    store: ChromaVectorStore,
) -> None:
    store.upsert(
        [
            make_embedded(
                source_id="runbook",
                vector=ALIGNED,
                extra={"doc_type": "runbook"},
            ),
            make_embedded(
                source_id="policy",
                vector=ORTHOGONAL,
                extra={"doc_type": "policy"},
            ),
            make_embedded(source_id="bare", vector=OPPOSING),
        ]
    )

    hits = store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"})

    assert [hit.chunk.source_id for hit in hits] == ["runbook"]
    assert dict(hits[0].chunk.metadata.extra) == {"doc_type": "runbook"}


def test_and_filters_require_every_extra_key(store: ChromaVectorStore) -> None:
    store.upsert(
        [
            make_embedded(
                source_id="both",
                vector=ALIGNED,
                extra={"doc_type": "runbook", "severity": "high"},
            ),
            make_embedded(
                source_id="type_only",
                vector=ORTHOGONAL,
                extra={"doc_type": "runbook", "severity": "low"},
            ),
            make_embedded(
                source_id="missing_sev",
                vector=OPPOSING,
                extra={"doc_type": "runbook"},
            ),
        ]
    )

    hits = store.search(
        ALIGNED,
        10,
        metadata_filters={"doc_type": "runbook", "severity": "high"},
    )

    assert [hit.chunk.source_id for hit in hits] == ["both"]


def test_missing_filter_key_excludes_chunks(store: ChromaVectorStore) -> None:
    store.upsert(
        [
            make_embedded(source_id="no-extra", vector=ALIGNED),
            make_embedded(
                source_id="other",
                vector=ORTHOGONAL,
                extra={"severity": "high"},
            ),
        ]
    )

    assert store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"}) == ()


def test_none_and_empty_filters_match_unfiltered_top_k(
    store: ChromaVectorStore,
) -> None:
    store.upsert(
        [
            make_embedded(source_id="a", vector=ALIGNED, index=0),
            make_embedded(source_id="b", vector=ORTHOGONAL, index=0),
        ]
    )

    unfiltered = [hit.chunk.source_id for hit in store.search(ALIGNED, 10)]
    assert [
        hit.chunk.source_id for hit in store.search(ALIGNED, 10, metadata_filters=None)
    ] == unfiltered
    assert [
        hit.chunk.source_id for hit in store.search(ALIGNED, 10, metadata_filters={})
    ] == unfiltered


def test_filters_apply_before_limit(store: ChromaVectorStore) -> None:
    """Nearest non-match must not consume the limit budget."""
    store.upsert(
        [
            make_embedded(
                source_id="nearest-non-match",
                vector=ALIGNED,
                extra={"doc_type": "policy"},
            ),
            make_embedded(
                source_id="match",
                vector=ORTHOGONAL,
                extra={"doc_type": "runbook"},
            ),
        ]
    )

    hits = store.search(ALIGNED, 1, metadata_filters={"doc_type": "runbook"})

    assert [hit.chunk.source_id for hit in hits] == ["match"]


def test_re_upsert_with_changed_extra_does_not_leave_stale_promoted_keys(
    store: ChromaVectorStore,
) -> None:
    """chromadb upsert merges metadata; stale `x:` keys must not survive replace."""
    store.upsert(
        [make_embedded(source_id="doc-1", vector=ALIGNED, extra={"tag": "old"})]
    )
    store.upsert(
        [make_embedded(source_id="doc-1", vector=ALIGNED, extra={"other": "new"})]
    )

    assert store.search(ALIGNED, 10, metadata_filters={"tag": "old"}) == ()
    hits = store.search(ALIGNED, 10, metadata_filters={"other": "new"})
    assert [hit.chunk.source_id for hit in hits] == ["doc-1"]
    assert dict(hits[0].chunk.metadata.extra) == {"other": "new"}


def test_reindex_filter_metadata_makes_legacy_extra_filterable(
    store: ChromaVectorStore,
) -> None:
    """Records written before `x:` promotion need an explicit reindex path."""
    store._collection.add(
        ids=["legacy-record"],
        embeddings=[list(ALIGNED)],
        documents=["legacy body"],
        metadatas=[
            {
                "source_id": "doc-1",
                "source_type": SourceType.KNOWLEDGE_DOCUMENT,
                "chunk_index": 0,
                "extra_json": json.dumps({"doc_type": "runbook"}, sort_keys=True),
            }
        ],
    )

    assert store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"}) == ()

    rewritten = store.reindex_filter_metadata()

    assert rewritten == 1
    hits = store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"})
    assert [hit.chunk.source_id for hit in hits] == ["doc-1"]
    assert dict(hits[0].chunk.metadata.extra) == {"doc_type": "runbook"}
    assert hits[0].chunk.content == "legacy body"


def test_reindex_filter_metadata_on_empty_collection_is_zero(
    store: ChromaVectorStore,
) -> None:
    assert store.reindex_filter_metadata() == 0


def test_reindex_filter_metadata_is_idempotent(store: ChromaVectorStore) -> None:
    store.upsert(
        [
            make_embedded(
                source_id="doc-1", vector=ALIGNED, extra={"doc_type": "runbook"}
            )
        ]
    )

    assert store.reindex_filter_metadata() == 1
    assert store.reindex_filter_metadata() == 1

    hits = store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"})
    assert [hit.chunk.source_id for hit in hits] == ["doc-1"]
    assert dict(hits[0].chunk.metadata.extra) == {"doc_type": "runbook"}


def test_reindex_filter_metadata_removes_stale_promoted_keys(
    store: ChromaVectorStore,
) -> None:
    """Reindex rewrites from extra_json and must drop leftover x: scalars."""
    store._collection.add(
        ids=["legacy-stale"],
        embeddings=[list(ALIGNED)],
        documents=["legacy body"],
        metadatas=[
            {
                "source_id": "doc-1",
                "source_type": SourceType.KNOWLEDGE_DOCUMENT,
                "chunk_index": 0,
                "extra_json": json.dumps({"doc_type": "runbook"}, sort_keys=True),
                "x:stale": "should-go",
            }
        ],
    )

    assert store.reindex_filter_metadata() == 1

    assert store.search(ALIGNED, 10, metadata_filters={"stale": "should-go"}) == ()
    hits = store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"})
    assert [hit.chunk.source_id for hit in hits] == ["doc-1"]
    raw = store._collection.get(ids=["legacy-stale"], include=["metadatas"])
    assert "x:stale" not in (raw["metadatas"][0] or {})


def test_failed_replacement_upsert_restores_existing_record(
    store: ChromaVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete-then-write must not accept data loss when the write fails."""
    store.upsert(
        [make_embedded(source_id="doc-1", vector=ALIGNED, extra={"tag": "old"})]
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("simulated upsert failure")

    monkeypatch.setattr(store._collection, "upsert", boom)

    with pytest.raises(ChromaStoreError, match="simulated upsert failure"):
        store.upsert(
            [make_embedded(source_id="doc-1", vector=ALIGNED, extra={"tag": "new"})]
        )

    hits = store.search(ALIGNED, 10, metadata_filters={"tag": "old"})
    assert [hit.chunk.source_id for hit in hits] == ["doc-1"]
    assert dict(hits[0].chunk.metadata.extra) == {"tag": "old"}
    assert hits[0].chunk.content == "body"


def test_partial_replacement_upsert_clears_new_ids_and_restores_snapshot(
    store: ChromaVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial primary write must not leave new IDs or block snapshot restore."""
    existing = make_embedded(
        source_id="doc-1",
        vector=ALIGNED,
        content="original body",
        extra={"tag": "old"},
    )
    store.upsert([existing])
    before = _raw_by_id(store)
    existing_id = _derive_id(existing.chunk)
    new_chunk = make_embedded(
        source_id="doc-2",
        vector=ORTHOGONAL,
        content="brand new",
        extra={"tag": "fresh"},
    )
    new_id = _derive_id(new_chunk.chunk)
    assert new_id not in before

    real_upsert = store._collection.upsert

    def partial_upsert(**kwargs: object) -> None:
        ids = list(kwargs["ids"])  # type: ignore[arg-type]
        embeddings = list(kwargs["embeddings"])  # type: ignore[arg-type]
        documents = list(kwargs["documents"])  # type: ignore[arg-type]
        metadatas = list(kwargs["metadatas"])  # type: ignore[arg-type]
        # Write only the newly introduced target, then fail — leaving a row
        # that would conflict with a naive snapshot ``add`` of the old ID.
        index = ids.index(new_id)
        real_upsert(
            ids=[ids[index]],
            embeddings=[embeddings[index]],
            documents=[documents[index]],
            metadatas=[metadatas[index]],
        )
        raise ValueError("partial upsert failure")

    monkeypatch.setattr(store._collection, "upsert", partial_upsert)

    with pytest.raises(ChromaStoreError, match="partial upsert failure") as raised:
        store.upsert(
            [
                make_embedded(
                    source_id="doc-1",
                    vector=ALIGNED,
                    content="replaced body",
                    extra={"tag": "new"},
                ),
                new_chunk,
            ]
        )

    assert isinstance(raised.value.__cause__, ValueError)
    assert _raw_by_id(store) == before
    assert new_id not in _raw_by_id(store)
    assert existing_id in before


def test_failed_replacement_upsert_reports_when_restoration_also_fails(
    store: ChromaVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.upsert(
        [make_embedded(source_id="doc-1", vector=ALIGNED, extra={"tag": "old"})]
    )

    def boom_upsert(*_args: object, **_kwargs: object) -> None:
        raise ValueError("primary write failed")

    def boom_add(*_args: object, **_kwargs: object) -> None:
        raise ValueError("restoration failed")

    monkeypatch.setattr(store._collection, "upsert", boom_upsert)
    monkeypatch.setattr(store._collection, "add", boom_add)

    with pytest.raises(ChromaStoreError, match="primary write failed") as raised:
        store.upsert(
            [make_embedded(source_id="doc-1", vector=ALIGNED, extra={"tag": "new"})]
        )

    message = str(raised.value)
    assert "restoration failed" in message
    assert isinstance(raised.value.__cause__, ValueError)


def test_failed_reindex_add_restores_existing_collection(
    store: ChromaVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store._collection.add(
        ids=["legacy-record"],
        embeddings=[list(ALIGNED)],
        documents=["legacy body"],
        metadatas=[
            {
                "source_id": "doc-1",
                "source_type": SourceType.KNOWLEDGE_DOCUMENT,
                "chunk_index": 0,
                "extra_json": json.dumps({"doc_type": "runbook"}, sort_keys=True),
            }
        ],
    )

    add_calls = {"n": 0}
    real_add = store._collection.add

    def flaky_add(*args: object, **kwargs: object) -> object:
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            raise ValueError("simulated reindex add failure")
        return real_add(*args, **kwargs)

    monkeypatch.setattr(store._collection, "add", flaky_add)

    with pytest.raises(ChromaStoreError, match="simulated reindex add failure"):
        store.reindex_filter_metadata()

    # Pre-promotion filter still misses; content and identity remain recoverable.
    assert store.search(ALIGNED, 10, metadata_filters={"doc_type": "runbook"}) == ()
    hits = store.search(ALIGNED, 10)
    assert len(hits) == 1
    assert hits[0].chunk.source_id == "doc-1"
    assert hits[0].chunk.content == "legacy body"
    assert dict(hits[0].chunk.metadata.extra) == {"doc_type": "runbook"}


def test_partial_reindex_add_clears_partial_rows_and_restores_snapshot(
    store: ChromaVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partial reindex ``add`` must not leave rewritten rows that block restore."""
    store.upsert(
        [
            make_embedded(
                source_id="doc-a",
                vector=ALIGNED,
                content="alpha",
                extra={"tag": "a"},
            ),
            make_embedded(
                source_id="doc-b",
                vector=ORTHOGONAL,
                content="beta",
                extra={"tag": "b"},
            ),
        ]
    )
    before = _raw_by_id(store)
    assert len(before) == 2

    add_calls = {"n": 0}
    real_add = store._collection.add

    def partial_add(**kwargs: object) -> object:
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            ids = list(kwargs["ids"])  # type: ignore[arg-type]
            embeddings = list(kwargs["embeddings"])  # type: ignore[arg-type]
            documents = list(kwargs["documents"])  # type: ignore[arg-type]
            metadatas = list(kwargs["metadatas"])  # type: ignore[arg-type]
            real_add(
                ids=ids[:1],
                embeddings=embeddings[:1],
                documents=documents[:1],
                metadatas=metadatas[:1],
            )
            raise ValueError("partial reindex add failure")
        return real_add(**kwargs)

    monkeypatch.setattr(store._collection, "add", partial_add)

    with pytest.raises(ChromaStoreError, match="partial reindex add failure") as raised:
        store.reindex_filter_metadata()

    assert isinstance(raised.value.__cause__, ValueError)
    assert add_calls["n"] >= 2  # primary partial write + restore path
    assert _raw_by_id(store) == before


def test_failed_reindex_reports_when_restoration_also_fails(
    store: ChromaVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.upsert(
        [
            make_embedded(
                source_id="doc-1", vector=ALIGNED, extra={"doc_type": "runbook"}
            )
        ]
    )

    def boom_add(*_args: object, **_kwargs: object) -> None:
        raise ValueError("reindex write failed")

    # Primary write and restoration both go through add after delete.
    monkeypatch.setattr(store._collection, "add", boom_add)

    with pytest.raises(ChromaStoreError, match="reindex write failed") as raised:
        store.reindex_filter_metadata()

    assert (
        "restoration" in str(raised.value).lower()
        or "recovery" in str(raised.value).lower()
    )
    assert isinstance(raised.value.__cause__, ValueError)
    # Both writes failed after delete — remaining non-atomic limitation.
    assert count(store) == 0


def test_empty_string_filter_value_matches(store: ChromaVectorStore) -> None:
    store.upsert(
        [
            make_embedded(source_id="empty", vector=ALIGNED, extra={"tag": ""}),
            make_embedded(source_id="filled", vector=ORTHOGONAL, extra={"tag": "x"}),
        ]
    )

    hits = store.search(ALIGNED, 10, metadata_filters={"tag": ""})

    assert [hit.chunk.source_id for hit in hits] == ["empty"]


def test_hostile_extra_keys_remain_filterable(store: ChromaVectorStore) -> None:
    extra = {"ünï:code": "قيمة", "a.b|c": "delimited", "": "empty key", "z": ""}
    store.upsert([make_embedded(source_id="hostile", vector=ALIGNED, extra=extra)])

    hits = store.search(ALIGNED, 1, metadata_filters={"ünï:code": "قيمة"})

    assert len(hits) == 1
    assert dict(hits[0].chunk.metadata.extra) == extra


def test_extra_keys_colliding_with_reserved_names_still_filter_via_extra(
    store: ChromaVectorStore,
) -> None:
    """Caller `title` in extra is filterable; owned title scalar is not."""
    store.upsert(
        [
            make_embedded(
                source_id="owned-title",
                vector=ALIGNED,
                title="runbook",
                extra={},
            ),
            make_embedded(
                source_id="extra-title",
                vector=ORTHOGONAL,
                title="real",
                extra={"title": "runbook"},
            ),
        ]
    )

    hits = store.search(ALIGNED, 10, metadata_filters={"title": "runbook"})

    assert [hit.chunk.source_id for hit in hits] == ["extra-title"]
    assert hits[0].chunk.metadata.title == "real"


@pytest.mark.parametrize("bad_filters", ["doc_type", ["doc_type"], 1])
def test_non_mapping_metadata_filters_are_rejected(
    store: ChromaVectorStore, bad_filters: object
) -> None:
    store.upsert([make_embedded()])
    with pytest.raises(ChromaStoreError, match="metadata_filters"):
        store.search(ALIGNED, 1, metadata_filters=bad_filters)  # type: ignore[arg-type]


def test_non_string_filter_key_or_value_is_rejected(store: ChromaVectorStore) -> None:
    store.upsert([make_embedded()])
    with pytest.raises(ChromaStoreError, match="metadata_filters"):
        store.search(
            ALIGNED,
            1,
            metadata_filters={1: "runbook"},  # type: ignore[dict-item]
        )
    with pytest.raises(ChromaStoreError, match="metadata_filters"):
        store.search(
            ALIGNED,
            1,
            metadata_filters={"doc_type": 1},  # type: ignore[dict-item]
        )


# --------------------------------------------------------------------------
# Collection configuration (§4.1, §4.2, §4.4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["ab", "my collection", "1.2.3.4", "x" * 64, "a..b", "-lead", "trail-"]
)
def test_invalid_collection_names_are_rejected(tmp_path: Path, name: str) -> None:
    """Includes the 64-character case, which chromadb 1.5.9 itself accepts."""
    with pytest.raises(ChromaStoreError, match="collection name"):
        ChromaVectorStore(settings(tmp_path / "chroma", collection=name))


def test_existing_cosine_collection_reopens(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    ChromaVectorStore(settings(path))
    assert ChromaVectorStore(settings(path)) is not None


def test_existing_non_cosine_collection_is_rejected(tmp_path: Path) -> None:
    """chromadb 1.5.9 ignores `configuration` when the collection already
    exists, so an l2 collection would be silently reused and every score would
    be wrong. The adapter must detect and refuse it (§4.2).
    """
    import chromadb
    from chromadb.config import Settings as ChromaClientSettings

    path = tmp_path / "chroma"
    path.mkdir(parents=True)
    client = chromadb.PersistentClient(
        path=str(path), settings=ChromaClientSettings(anonymized_telemetry=False)
    )
    client.get_or_create_collection(
        name=COLLECTION,
        configuration={"hnsw": {"space": "l2"}},
        embedding_function=None,
    )
    with pytest.raises(ChromaStoreError, match="distance space"):
        ChromaVectorStore(settings(path))


def test_two_sequential_adapters_share_one_collection(tmp_path: Path) -> None:
    """Sequential Streamlit reruns construct the adapter again on the same path.

    chromadb 1.5.9 caches its client system per path and raises ValueError when
    a second client disagrees on settings, so this passes only while
    `_client_settings()` stays deterministic (§4.4). There is no fallback: if
    this fails, fix the constructor, not the test.
    """
    path = tmp_path / "chroma"
    first = ChromaVectorStore(settings(path))
    first.upsert([make_embedded(content="written by the first adapter")])

    second = ChromaVectorStore(settings(path))
    results = second.search(ALIGNED, 1)
    assert len(results) == 1
    assert results[0].chunk.content == "written by the first adapter"


def test_reopening_does_not_recreate_the_collection(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    first = ChromaVectorStore(settings(path))
    first.upsert([make_embedded(index=0), make_embedded(index=1)])
    assert count(ChromaVectorStore(settings(path))) == 2


# --------------------------------------------------------------------------
# No default embedding function (§11)
# --------------------------------------------------------------------------


def test_no_default_embedding_model_is_downloaded_or_initialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Construct, write, reopen, and search without touching the network.

    chromadb 1.5.9 exposes no environment variable for the model cache: the
    path is the class attribute `ONNXMiniLM_L6_V2.DOWNLOAD_PATH`, evaluated at
    import time from `Path.home()`. Redirecting that attribute is therefore the
    only reliable way to prove nothing was fetched (§1 step 4).

    Sockets are blocked only after chromadb is imported, so import-time setup is
    not what fails. Absence of `onnxruntime` from `sys.modules` is deliberately
    not used as evidence: chromadb 1.5.9 depends on it unconditionally.
    """
    import socket

    import chromadb  # noqa: F401 - must be imported before sockets are blocked
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
        ONNXMiniLM_L6_V2,
    )

    cache = tmp_path / "model-cache"
    cache.mkdir()
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", cache)

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("the adapter attempted network access")

    monkeypatch.setattr(socket, "socket", blocked)

    path = tmp_path / "chroma"
    store = ChromaVectorStore(settings(path))
    store.upsert([make_embedded()])
    results = ChromaVectorStore(settings(path)).search(ALIGNED, 1)

    assert len(results) == 1
    assert list(cache.iterdir()) == []


# --------------------------------------------------------------------------
# Corrupt records (§11)
# --------------------------------------------------------------------------


def valid_record(store: ChromaVectorStore) -> dict[str, object]:
    """Write one good record and hand back its raw persisted metadata."""
    store.upsert([make_embedded(title="real")])
    # Deliberately reaches past the public surface: corrupting a record has to
    # bypass the encoder that would otherwise reject the malformed value.
    raw = store._collection.get(include=["metadatas"])
    return dict(raw["metadatas"][0])


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "missing source_id",
            lambda m: {k: v for k, v in m.items() if k != "source_id"},
        ),
        ("blank source_id", lambda m: {**m, "source_id": "   "}),
        ("blank source_type", lambda m: {**m, "source_type": "   "}),
        ("non-string source_type", lambda m: {**m, "source_type": 42}),
        ("negative chunk_index", lambda m: {**m, "chunk_index": -1}),
        ("non-integer chunk_index", lambda m: {**m, "chunk_index": "zero"}),
        ("malformed extra_json", lambda m: {**m, "extra_json": "{not json"}),
        ("non-mapping extra_json", lambda m: {**m, "extra_json": "[1, 2]"}),
        ("non-string extra value", lambda m: {**m, "extra_json": '{"a": 1}'}),
        ("non-string title", lambda m: {**m, "title": 42}),
    ],
)
def test_corrupt_records_raise_chroma_store_error(
    store: ChromaVectorStore, label: str, mutate: object
) -> None:
    """Persisted data can be corrupt regardless of what the encoder allows.

    Writing through the private handle is the only way to produce these states,
    since the public path validates on the way in.
    """
    metadata = mutate(valid_record(store))
    store._collection.upsert(
        ids=["corrupt-1"],
        embeddings=[list(ALIGNED)],
        documents=["body"],
        metadatas=[metadata],
    )
    with pytest.raises(ChromaStoreError, match="corrupt-1"):
        store.search(ALIGNED, 10)


# --------------------------------------------------------------------------
# Process-restart proof (§12)
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

_WRITER = """
import sys
from pathlib import Path

from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import ChromaVectorStore

store = ChromaVectorStore(
    ChromaSettings(persist_path=Path(sys.argv[1]), collection="kernector_knowledge")
)
metadata = SourceMetadata(
    reference=SourceReference("restart-doc", SourceType.KNOWLEDGE_DOCUMENT),
    title="Survives restart",
    provider="jira",
    content_format="markdown",
    extra={"tags_json": '["persisted"]'},
)
chunk = DocumentChunk(metadata=metadata, index=3, content="written by the writer")
store.upsert([EmbeddedChunk(chunk=chunk, vector=[1.0, 0.0, 0.0])])
"""

_READER = """
import sys
from pathlib import Path

from domain.knowledge import SourceType
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import ChromaVectorStore

store = ChromaVectorStore(
    ChromaSettings(persist_path=Path(sys.argv[1]), collection="kernector_knowledge")
)
results = store.search([1.0, 0.0, 0.0], 5)
assert len(results) == 1, f"expected one record, got {len(results)}"

scored = results[0]
chunk = scored.chunk
assert chunk.content == "written by the writer", chunk.content
assert chunk.index == 3, chunk.index
assert chunk.metadata.title == "Survives restart", chunk.metadata.title
assert chunk.metadata.provider == "jira", chunk.metadata.provider
assert chunk.metadata.content_format == "markdown", chunk.metadata.content_format
assert chunk.metadata.reference.source_id == "restart-doc"
assert chunk.metadata.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT
assert dict(chunk.metadata.extra) == {"tags_json": '["persisted"]'}, chunk.metadata.extra
assert abs(scored.score - 1.0) < 1e-6, scored.score
print("reader ok")
"""


def test_records_survive_a_process_restart(tmp_path: Path) -> None:
    """Persistence proven across real processes, not a second client in one.

    A same-process client reuses chromadb's cached client system, so it could
    pass on in-memory state alone and prove nothing about what reached disk.

    `cwd=REPO_ROOT` is load-bearing: `pythonpath = ["."]` in pyproject.toml
    applies to pytest only, not to a bare subprocess, so without it neither
    child could import `domain` or `infrastructure` (§12).
    """
    path = tmp_path / "chroma"

    writer = subprocess.run(
        [sys.executable, "-c", _WRITER, str(path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert writer.returncode == 0, writer.stderr

    reader = subprocess.run(
        [sys.executable, "-c", _READER, str(path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert reader.returncode == 0, reader.stderr
    assert "reader ok" in reader.stdout
