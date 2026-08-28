"""Ingest normalized knowledge sources into the vector store through ports."""

from collections.abc import Sequence

from application.chunking import chunk_document
from application.contracts import IngestRequest, IngestResponse
from application.errors import ApplicationValidationError
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceDocument,
    SourceReference,
)
from domain.ports import EmbeddingModel, VectorStore


class IngestFailure(RuntimeError):
    """Ingest failed, with an explicit signal about vector-store mutation.

    Attributes:
        vector_mutation_started (bool): True when ``delete_source`` or ``upsert``
            may have run for this request, so callers must not restore a prior
            ready catalog row blindly.
    """

    def __init__(
        self,
        message: str,
        *,
        vector_mutation_started: bool,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.vector_mutation_started = vector_mutation_started
        self.__cause__ = cause


class IngestKnowledge:
    """Turns `SourceDocument` inputs into embedded chunks the store holds.

    Accepts ports and primitive settings only: the application layer must not
    import `infrastructure` or its configuration dataclasses.
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        *,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        self._embedding_model = embedding_model
        self._vector_store = vector_store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def execute(self, request: IngestRequest) -> IngestResponse:
        """Chunk, embed, and store every document in `request`.

        Every source is chunked, embedded, and validated before the first
        deletion, so an embedding or validation failure cannot leave a source
        deleted and unreplaced. The per-source delete/upsert pair itself is not
        atomic: the vector index is derived, rebuildable data, and a later
        successful re-ingest repairs a partial storage failure.

        Args:
            request: The sources to ingest. Its own contract has already
                validated the collections by the time it arrives here.

        Returns:
            The accepted source identifiers and the total chunks stored.

        Raises:
            ApplicationValidationError: A non-empty `tickets` collection,
                duplicate source references, an embedding result whose length
                disagrees with the chunk count, or — propagated from
                `chunk_document` — an invalid document or chunk setting.
            IngestFailure: Embedding or vector-store failure, annotated with
                whether vector mutation may have started.
        """
        if request.tickets:
            raise ApplicationValidationError(
                f"tickets are not ingested yet, got {len(request.tickets)}; "
                "pass documents only until Ticket -> SourceDocument mapping "
                "ships in its own ticket"
            )
        _reject_duplicate_references(request.documents)
        try:
            chunks_by_document = tuple(
                self._chunk(document) for document in request.documents
            )
            all_chunks = tuple(
                chunk for chunks in chunks_by_document for chunk in chunks
            )
            vectors = self._embedding_model.embed_documents(
                [chunk.content for chunk in all_chunks]
            )
        except ApplicationValidationError:
            raise
        except Exception as error:
            raise IngestFailure(
                str(error),
                vector_mutation_started=False,
                cause=error,
            ) from error
        if len(vectors) != len(all_chunks):
            raise ApplicationValidationError(
                f"embedding returned {len(vectors)} vector(s) for "
                f"{len(all_chunks)} chunk(s)"
            )
        embedded = tuple(
            EmbeddedChunk(chunk=chunk, vector=vector)
            for chunk, vector in zip(all_chunks, vectors, strict=True)
        )
        try:
            for document, records in zip(
                request.documents,
                _regroup(embedded, chunks_by_document),
                strict=True,
            ):
                self._vector_store.delete_source(document.reference)
                self._vector_store.upsert(records)
        except Exception as error:
            raise IngestFailure(
                str(error),
                vector_mutation_started=True,
                cause=error,
            ) from error
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=len(embedded),
        )

    def _chunk(self, document: SourceDocument) -> tuple[DocumentChunk, ...]:
        """Apply this instance's chunk settings to one document."""
        return chunk_document(
            document,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )


def _regroup(
    embedded: Sequence[EmbeddedChunk],
    chunks_by_document: Sequence[Sequence[DocumentChunk]],
) -> tuple[tuple[EmbeddedChunk, ...], ...]:
    """Split the flat embedded batch back into one group per document.

    The batch is flat while it is embedded and validated, so every vector is in
    hand before anything is deleted. The groups exist because deletion is
    scoped to a single source: each source's replacement must be upserted
    immediately after its own old records are removed.
    """
    groups: list[tuple[EmbeddedChunk, ...]] = []
    position = 0
    for chunks in chunks_by_document:
        groups.append(tuple(embedded[position : position + len(chunks)]))
        position += len(chunks)
    return tuple(groups)


def _reject_duplicate_references(documents: Sequence[SourceDocument]) -> None:
    """Refuse two inputs that claim the same complete `SourceReference`.

    Load-bearing, not defensive. Deletion is scoped per source, so two inputs
    sharing a reference would make the second iteration's `delete_source` wipe
    the chunks the first iteration had just upserted. The store's own
    duplicate-identity guard cannot see it, because the two sources arrive in
    separate `upsert` batches.

    Raises:
        ApplicationValidationError: If any reference appears more than once.
    """
    seen: set[SourceReference] = set()
    for document in documents:
        reference = document.reference
        if reference in seen:
            raise ApplicationValidationError(
                f"duplicate source reference {reference.source_type}:"
                f"{reference.source_id} in one request; each source may appear "
                "at most once"
            )
        seen.add(reference)
