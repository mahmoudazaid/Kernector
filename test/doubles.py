"""Shared test doubles for the ingest suites.

Not collected by pytest: the basename lacks the `test_` prefix. Imported as
`from test.doubles import ...`, which works because `test/__init__.py` exists
and `pythonpath = ["."]` puts the repo root ahead of the stdlib `test` package
— the same mechanism `test/domain/test_domain_boundaries.py` uses to reach
`test.architecture.import_scan`.
"""

import hashlib
from collections.abc import Sequence

from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    ScoredChunk,
    SourceReference,
    Vector,
)

_DIMENSION = 4


def vector_for(text: str) -> list[float]:
    """The vector `StubEmbeddingModel` assigns to `text`.

    Public so a test can name the vector a chunk should have been paired with
    instead of re-deriving it.

    Every component is >= 1.0, so the result is never the zero vector: cosine
    distance is undefined for a zero vector and the integration suite embeds
    through real Chroma. Derived from SHA-256 rather than the built-in `hash()`,
    which is salted per process and would differ between runs.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [1.0 + digest[index] for index in range(_DIMENSION)]


class StubEmbeddingModel:
    """An EmbeddingModel that is deterministic and offline.

    The same text always yields the same vector, and every vector has the same
    width, which the Chroma adapter requires within one batch.
    """

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        return [vector_for(text) for text in texts]

    def embed_query(self, text: str) -> Vector:
        return vector_for(text)


class WrongLengthEmbeddingModel:
    """An EmbeddingModel that returns the wrong number of vectors.

    `offset` is added to the batch size: -1 drops a vector, +1 invents one. The
    vectors it does return are individually valid — right width, non-zero,
    finite — so nothing but an explicit count check catches the defect.
    """

    def __init__(self, offset: int) -> None:
        self._offset = offset

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        wanted = max(len(texts) + self._offset, 0)
        return [vector_for(f"filler-{index}") for index in range(wanted)]

    def embed_query(self, text: str) -> Vector:
        return vector_for(text)


class EmbeddingUnavailable(RuntimeError):
    """Stands in for a provider outage raised by `FailingEmbeddingModel`."""


class FailingEmbeddingModel:
    """An EmbeddingModel that fails before returning anything.

    The use case must let this propagate unchanged and must not have mutated
    the store on the way out.
    """

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        raise EmbeddingUnavailable("embedding provider is unavailable")

    def embed_query(self, text: str) -> Vector:
        raise EmbeddingUnavailable("embedding provider is unavailable")


def record_key(chunk: DocumentChunk) -> tuple[str, str, int]:
    """The identity `InMemoryVectorStore` stores a chunk under.

    Mirrors the `(source_type, source_id, chunk_index)` identity the Chroma
    adapter hashes into its record IDs, so this double replaces a re-upserted
    chunk in place exactly as the real store does.
    """
    reference = chunk.reference
    return (str(reference.source_type), reference.source_id, chunk.index)


class InMemoryVectorStore:
    """A dict-backed VectorStore, so use-case tests need no real store.

    `records` is public: assert against stored state, never against which
    private helpers were called.

    `search` returns records in insertion order, NOT by similarity, and ignores
    the query vector entirely. Ranking is the Chroma adapter's behavior and
    `test/infrastructure/vectorstore/test_chroma.py` owns it; never assert
    ranking through this double.
    """

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, int], EmbeddedChunk] = {}

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        for item in embedded:
            self.records[record_key(item.chunk)] = item

    def search(self, vector: Vector, limit: int) -> Sequence[ScoredChunk]:
        if limit <= 0:
            return ()
        return tuple(
            ScoredChunk(chunk=item.chunk, score=1.0)
            for item in list(self.records.values())[:limit]
        )

    def delete_source(self, reference: SourceReference) -> None:
        scope = (str(reference.source_type), reference.source_id)
        for key in [key for key in self.records if key[:2] == scope]:
            del self.records[key]
