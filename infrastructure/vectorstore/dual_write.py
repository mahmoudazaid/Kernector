"""VectorStore decorator that mirrors mutations into a LexicalIndex."""

from collections.abc import Mapping, Sequence

from domain.errors import VectorStoreError
from domain.knowledge import (
    ChunkPage,
    EmbeddedChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    Vector,
)
from domain.ports import LexicalIndex, VectorStore


class DualWriteVectorStore:
    """Delegates search to ``vector``; mirrors upsert/delete to ``lexical``."""

    def __init__(self, vector: VectorStore, lexical: LexicalIndex) -> None:
        self._vector = vector
        self.lexical = lexical

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        self._vector.upsert(embedded)
        self.lexical.upsert(embedded)

    def search(
        self,
        vector: Vector,
        limit: int,
        *,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> Sequence[ScoredChunk]:
        return self._vector.search(
            vector, limit, metadata_filters=metadata_filters
        )

    def delete_source(self, reference: SourceReference) -> None:
        self._vector.delete_source(reference)
        self.lexical.delete_source(reference)

    def update_source_metadata(
        self, reference: SourceReference, metadata: SourceMetadata
    ) -> int:
        """Update the vector store first, then the lexical mirror.

        A lexical failure is raised as ``VectorStoreError`` so callers fail
        closed. Retrying converges: the vector rewrite is idempotent, and the
        lexical index is rebuilt from the vector store on startup.
        """
        count = self._vector.update_source_metadata(reference, metadata)
        try:
            self.lexical.update_source_metadata(reference, metadata)
        except Exception as error:
            raise VectorStoreError(
                f"lexical mirror update failed for {reference.source_type}:"
                f"{reference.source_id}: {error}"
            ) from error
        return count

    def list_source_chunks(
        self,
        reference: SourceReference,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> ChunkPage:
        return self._vector.list_source_chunks(
            reference, limit=limit, offset=offset
        )
