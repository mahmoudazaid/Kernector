"""BM25 implementation of the LexicalIndex port."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from rank_bm25 import BM25Okapi

from domain.knowledge import EmbeddedChunk, ScoredChunk, SourceReference
from domain.errors import VectorStoreError

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens; no stemming (lab convention)."""
    return _TOKEN_PATTERN.findall(text.lower())


def _record_key(chunk_ref: SourceReference, index: int) -> tuple[str, str, int]:
    return (str(chunk_ref.source_type), chunk_ref.source_id, index)


def _matches_extra(
    embedded: EmbeddedChunk, metadata_filters: Mapping[str, str]
) -> bool:
    extra = embedded.chunk.metadata.extra
    return all(extra.get(key) == value for key, value in metadata_filters.items())


class Bm25LexicalIndex:
    """In-memory BM25Okapi index over embedded chunk text."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, int], EmbeddedChunk] = {}
        self._order: list[tuple[str, str, int]] = []
        self._bm25: BM25Okapi | None = None

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        if not embedded:
            return
        for item in embedded:
            if not isinstance(item, EmbeddedChunk):
                raise VectorStoreError(
                    f"lexical upsert requires EmbeddedChunk, got {item!r}"
                )
            key = _record_key(item.chunk.reference, item.chunk.index)
            if key not in self._records:
                self._order.append(key)
            self._records[key] = item
        self._rebuild()

    def delete_source(self, reference: SourceReference) -> None:
        scope = (str(reference.source_type), reference.source_id)
        survivors = [key for key in self._order if key[:2] != scope]
        if len(survivors) == len(self._order):
            return
        for key in list(self._records):
            if key[:2] == scope:
                del self._records[key]
        self._order = survivors
        self._rebuild()

    def search(
        self,
        query: str,
        limit: int,
        *,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> Sequence[ScoredChunk]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
            or not self._records
            or self._bm25 is None
        ):
            return ()
        filters = metadata_filters or {}
        if filters is not None and not isinstance(filters, Mapping):
            raise VectorStoreError(
                f"metadata_filters must be a mapping, got {type(filters)!r}"
            )
        tokens = tokenize(query)
        if not tokens:
            return ()
        scores = self._bm25.get_scores(tokens)
        ranked: list[ScoredChunk] = []
        for key, score in zip(self._order, scores, strict=True):
            item = self._records[key]
            if filters and not _matches_extra(item, filters):
                continue
            ranked.append(ScoredChunk(chunk=item.chunk, score=float(score)))
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return tuple(ranked[:limit])

    def _rebuild(self) -> None:
        if not self._order:
            self._bm25 = None
            return
        corpus = [
            tokenize(self._records[key].chunk.content) for key in self._order
        ]
        self._bm25 = BM25Okapi(corpus)
