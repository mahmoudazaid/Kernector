"""VectorStore decorator that mirrors mutations into a LexicalIndex."""

from collections.abc import Mapping, Sequence

from domain.knowledge import EmbeddedChunk, ScoredChunk, SourceReference, Vector
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
