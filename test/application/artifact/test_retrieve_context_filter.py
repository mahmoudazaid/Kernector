"""contexts[] filters exact and hybrid paths before the final limit (#373)."""

from __future__ import annotations

from application.artifact.lookup import LookupArtifacts
from application.contracts import RetrieveRequest
from application.retrieve_knowledge import RetrieveKnowledge
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ContextAssignment
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore, StubEmbeddingModel, vector_for


class _Index:
    def __init__(self, *descriptors: ArtifactDescriptor) -> None:
        self._descriptors = {d.reference: d for d in descriptors}
        self._by_key: dict[str, list[ArtifactDescriptor]] = {}
        for descriptor in descriptors:
            for key in descriptor.external_keys:
                self._by_key.setdefault(key, []).append(descriptor)

    def upsert(self, descriptor: ArtifactDescriptor) -> None: ...
    def remove(self, reference: SourceReference) -> None: ...
    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        return self._descriptors.get(reference)

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
        return tuple(self._descriptors.values())


def test_contexts_api_contract_filters_exact_and_hybrid() -> None:
    api = ArtifactDescriptor(
        reference=SourceReference("acme/proj:api/openapi.yaml", "github"),
        revision="sha",
        kind=ArtifactKind.API_SPEC,
        contexts=(
            ContextAssignment("api_contract", "openapi_to_api_contract"),
            ContextAssignment("backend", "role_default"),
        ),
        external_keys=("cancelOrder",),
        title="openapi",
    )
    code = ArtifactDescriptor(
        reference=SourceReference("acme/proj:orders/cancel.py", "github"),
        revision="sha2",
        kind=ArtifactKind.CODE_FILE,
        contexts=(ContextAssignment("backend", "role_default"),),
        title="cancel.py",
    )
    store = InMemoryVectorStore()
    for source_id, body in (
        ("acme/proj:api/openapi.yaml", "POST cancel order api contract"),
        ("acme/proj:orders/cancel.py", "cancel order implementation"),
    ):
        chunk = DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, "github"), title=source_id),
            index=0,
            content=body,
        )
        store.upsert([EmbeddedChunk(chunk=chunk, vector=vector_for(body))])

    index = _Index(api, code)
    lookup = LookupArtifacts(
        index,
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: ("prj_proj",),
    )
    retrieve = RetrieveKnowledge(
        StubEmbeddingModel(),
        store,
        max_input_length=10_000,
        artifact_lookup=lookup,
        project_ids_for=lambda _ref: ("prj_proj",),
        descriptor_for=index.get,
    )

    response = retrieve.execute(
        RetrieveRequest(
            query="cancel order",
            retrieval_limit=5,
            project_id="prj_proj",
            contexts=("api_contract",),
            identifiers=("cancelOrder",),
        )
    )

    assert [hit.chunk.source_id for hit in response.hits] == [
        "acme/proj:api/openapi.yaml"
    ]
