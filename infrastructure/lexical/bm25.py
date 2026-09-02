"""BM25 implementation of the LexicalIndex port."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from rank_bm25 import BM25Okapi

from domain.knowledge import EmbeddedChunk, ScoredChunk, SourceReference
from domain.errors import VectorStoreError

# Unicode letters/numbers with optional hyphenated continuations (ERR-4021).
# ``\w`` is Unicode-aware; exclude underscore so tokens stay lexical words.
_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)

# Placeholder for documents that tokenize to nothing so BM25Okapi never sees [].
_EMPTY_DOC_PLACEHOLDER = "\0"


def tokenize(text: str) -> list[str]:
    """Unicode-aware tokens; casefold; no stemming. Keeps hyphenated ids."""
    return _TOKEN_PATTERN.findall(text.casefold())


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
        self._doc_tokens: list[list[str]] = []
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
        if not isinstance(filters, Mapping):
            raise VectorStoreError(
                f"metadata_filters must be a mapping, got {type(filters)!r}"
            )
        query_tokens = tokenize(query)
        if not query_tokens:
            return ()
        query_set = set(query_tokens)
        scores = self._bm25.get_scores(query_tokens)
        ranked: list[ScoredChunk] = []
        for key, score, doc_tokens in zip(
            self._order, scores, self._doc_tokens, strict=True
        ):
            if not query_set.intersection(doc_tokens):
                continue
            item = self._records[key]
            if filters and not _matches_extra(item, filters):
                continue
            ranked.append(ScoredChunk(chunk=item.chunk, score=float(score)))
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return tuple(ranked[:limit])

    def _rebuild(self) -> None:
        if not self._order:
            self._bm25 = None
            self._doc_tokens = []
            return
        tokenized = [
            tokenize(self._records[key].chunk.content) for key in self._order
        ]
        self._doc_tokens = tokenized
        if not any(tokenized):
            # All punctuation / empty-token docs: BM25Okapi([]) divides by zero.
            self._bm25 = None
            return
        corpus = [
            tokens if tokens else [_EMPTY_DOC_PLACEHOLDER] for tokens in tokenized
        ]
        self._bm25 = BM25Okapi(corpus)
