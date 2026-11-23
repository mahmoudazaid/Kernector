"""Exact lookup merges ahead of hybrid; project leakage excluded (#373)."""

from __future__ import annotations

from application.artifact.lookup import LookupArtifacts
from application.contracts import RetrieveRequest
from application.retrieve_knowledge import RetrieveKnowledge
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore, StubEmbeddingModel, vector_for


def _chunk(source_id: str, content: str, source_type: str = "jira") -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, source_type),
            title=source_id,
        ),
        index=0,
        content=content,
    )


class _Index:
    def __init__(self, *descriptors: ArtifactDescriptor) -> None:
        self._descriptors = descriptors
        self._by_key: dict[str, list[ArtifactDescriptor]] = {}
        for descriptor in descriptors:
            for key in descriptor.external_keys:
                self._by_key.setdefault(key, []).append(descriptor)

    def upsert(self, descriptor: ArtifactDescriptor) -> None: ...
    def remove(self, reference: SourceReference) -> None: ...
    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        for descriptor in self._descriptors:
            if descriptor.reference == reference:
                return descriptor
        return None

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        found: list[ArtifactDescriptor] = []
        seen: set[tuple[str, str]] = set()
        for key in keys:
            for descriptor in self._by_key.get(key, ()):
                ref = (
                    descriptor.reference.source_type,
                    descriptor.reference.source_id,
                )
                if ref not in seen:
                    seen.add(ref)
                    found.append(descriptor)
        return tuple(found)

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        return self._descriptors


def test_exact_hit_absent_from_hybrid_top_k_still_returned_first() -> None:
    proj = ArtifactDescriptor(
        reference=SourceReference("cloud/PROJ:PROJ-123", "jira"),
        revision="r1",
        kind=ArtifactKind.STORY,
        external_keys=("PROJ-123",),
        title="Cancel order story",
    )
    # Hybrid store only has a decoy payment story with similar wording.
    store = InMemoryVectorStore()
    decoy = _chunk("cloud/PAY:PAY-77", "Cancel payment unpaid order rules")
    store.upsert([EmbeddedChunk(chunk=decoy, vector=vector_for(decoy.content))])
    # Exact story has no vector chunks — synthetic exact hit still wins.
    lookup = LookupArtifacts(
        _Index(proj),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda ref: (
            ("prj_proj",) if "PROJ" in ref.source_id else ("prj_pay",)
        ),
    )
    retrieve = RetrieveKnowledge(
        StubEmbeddingModel(),
        store,
        max_input_length=10_000,
        artifact_lookup=lookup,
        project_ids_for=lambda ref: (
            ("prj_proj",) if "PROJ" in ref.source_id else ("prj_pay",)
        ),
    )

    response = retrieve.execute(
        RetrieveRequest(
            query="cancel order rules PROJ-123",
            retrieval_limit=2,
            project_id="prj_proj",
        )
    )

    assert response.hits[0].chunk.source_id == "cloud/PROJ:PROJ-123"
    assert all("PAY" not in hit.chunk.source_id for hit in response.hits)


def test_out_of_scope_decoy_excluded_even_if_hybrid_ranks_it() -> None:
    pay = ArtifactDescriptor(
        reference=SourceReference("cloud/PAY:PAY-77", "jira"),
        revision="r1",
        kind=ArtifactKind.STORY,
        external_keys=("PAY-77",),
        title="Cancel payment",
    )
    store = InMemoryVectorStore()
    decoy = _chunk("cloud/PAY:PAY-77", "cancel order rules")
    store.upsert([EmbeddedChunk(chunk=decoy, vector=vector_for(decoy.content))])
    lookup = LookupArtifacts(
        _Index(pay),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: ("prj_pay",),
    )
    retrieve = RetrieveKnowledge(
        StubEmbeddingModel(),
        store,
        max_input_length=10_000,
        artifact_lookup=lookup,
        project_ids_for=lambda _ref: ("prj_pay",),
    )

    response = retrieve.execute(
        RetrieveRequest(
            query="cancel order rules",
            retrieval_limit=5,
            project_id="prj_proj",
            identifiers=("PAY-77",),
        )
    )

    assert response.hits == ()
