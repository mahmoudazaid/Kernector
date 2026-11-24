"""Exact identifier pins a source without dropping its hybrid chunks (#373)."""

from __future__ import annotations

from datetime import UTC, datetime

from application.artifact.lookup import LookupArtifacts
from application.contracts import RetrieveRequest
from application.retrieve_knowledge import RetrieveKnowledge
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore, StubEmbeddingModel, vector_for

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_SOURCE = "cloud/PROJ:PROJ-1"


def _chunk(source_id: str, index: int, content: str) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, "jira"),
            title="Account lockout",
        ),
        index=index,
        content=content,
    )


class _Index:
    def __init__(self, descriptor: ArtifactDescriptor) -> None:
        self._descriptor = descriptor

    def upsert(self, descriptor: ArtifactDescriptor) -> None: ...
    def remove(self, reference: SourceReference) -> None: ...
    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        if reference == self._descriptor.reference:
            return self._descriptor
        return None

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        if any(key in self._descriptor.external_keys for key in keys):
            return (self._descriptor,)
        return ()

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        return (self._descriptor,)


def test_naming_identifier_keeps_hybrid_answer_chunk_from_same_source() -> None:
    descriptor = ArtifactDescriptor(
        reference=SourceReference(_SOURCE, "jira"),
        revision="r1",
        kind=ArtifactKind.STORY,
        external_keys=("PROJ-1",),
        title="Account lockout",
    )
    answer = _chunk(
        _SOURCE,
        2,
        "Acceptance criteria: lock the account after 5 failed attempts",
    )
    summary = _chunk(_SOURCE, 0, "Summary of PROJ-1")
    mid = _chunk(_SOURCE, 1, "Description body")
    other = _chunk("handbook", 0, "unrelated handbook note")
    store = InMemoryVectorStore()
    # Insertion order is search order for InMemoryVectorStore: put answer first.
    store.upsert(
        [
            EmbeddedChunk(chunk=answer, vector=vector_for(answer.content)),
            EmbeddedChunk(chunk=mid, vector=vector_for(mid.content)),
            EmbeddedChunk(chunk=summary, vector=vector_for(summary.content)),
            EmbeddedChunk(chunk=other, vector=vector_for(other.content)),
        ]
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(
        CatalogDocument(
            reference=descriptor.reference,
            file_name="issue.md",
            title="Account lockout",
            content_format="markdown",
            status=CatalogStatus.READY,
            created_at=_NOW,
            updated_at=_NOW,
            chunk_count=3,
            error=None,
            revision="r1",
        )
    )
    retrieve = RetrieveKnowledge(
        StubEmbeddingModel(),
        store,
        max_input_length=10_000,
        artifact_lookup=LookupArtifacts(
            _Index(descriptor),
            catalog,
            project_ids_for=lambda _ref: ("prj_proj",),
        ),
    )

    response = retrieve.execute(
        RetrieveRequest(
            query="acceptance criteria for PROJ-1 lockout",
            retrieval_limit=3,
        )
    )

    keys = [(hit.chunk.source_id, hit.chunk.index) for hit in response.hits]
    assert keys[0] == (_SOURCE, 0)  # exact pin (list_source_chunks limit=1)
    assert (_SOURCE, 2) in keys  # hybrid answer chunk kept
    assert len(response.hits) == 3
