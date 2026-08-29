"""Chroma implementation of the `VectorStore` port. Verified against chromadb 1.5.9."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from math import isfinite

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaClientSettings
from chromadb.errors import ChromaError

from domain.errors import DomainValidationError
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    Vector,
)
from infrastructure.config import ChromaSettings

_COSINE = "cosine"
_MIN_NAME_LENGTH = 3
_MAX_NAME_LENGTH = 63
_NAME_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]")
_IPV4_PATTERN = re.compile(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}")

# Bumping this re-derives every record ID at once, orphaning the entire existing
# collection. That is now reconcilable: `delete_source` scopes removal by the
# stored metadata rather than by derived ID, so a full re-ingest of every source
# converges the store onto the new scheme.
_ID_SCHEME_VERSION = 1

# Scalar metadata keys the adapter owns. Caller keys never land in this
# namespace: the whole of `SourceMetadata.extra` travels as one JSON envelope
# under `_KEY_EXTRA_JSON`, so a caller key named "title" cannot shadow the real
# title, and #86 stays free to promote chosen fields into scalar metadata.
_KEY_SOURCE_ID = "source_id"
_KEY_SOURCE_TYPE = "source_type"
_KEY_CHUNK_INDEX = "chunk_index"
_KEY_TITLE = "title"
_KEY_PROVIDER = "provider"
_KEY_CONTENT_FORMAT = "content_format"
_KEY_EXTRA_JSON = "extra_json"


class ChromaStoreError(RuntimeError):
    """Raised when the Chroma adapter cannot honor the VectorStore contract."""


def _client_settings() -> ChromaClientSettings:
    """Client settings, identical on every construction for a given path.

    chromadb 1.5.9 caches its client system per path and raises
    `ValueError: An instance of Chroma already exists for <path> with different
    settings` when a second client on the same path disagrees. Sequential
    Streamlit reruns depend on this staying deterministic (§4.4), so it must
    never be derived from mutable state.
    """
    return ChromaClientSettings(anonymized_telemetry=False)


def _canonical_json(payload: object) -> str:
    """Byte-stable JSON: identical output for identical input, every run."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _derive_id(chunk: DocumentChunk) -> str:
    """Collision-safe record ID derived from the chunk's identity.

    Hashing a canonical JSON object rather than joining fields with a delimiter
    means a `source_id` containing that delimiter cannot forge another chunk's
    identity: field boundaries are carried by the JSON structure, not by a
    separator character that can appear inside a value.

    The identity fields are also stored in metadata (§6). Decoding reads them
    from there and never attempts to reverse this hash.
    """
    payload = {
        "scheme": _ID_SCHEME_VERSION,
        "source_type": str(chunk.metadata.reference.source_type),
        "source_id": chunk.metadata.reference.source_id,
        "chunk_index": chunk.index,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _describe(chunk: DocumentChunk) -> str:
    """Human-readable chunk identity for error messages."""
    reference = chunk.metadata.reference
    return f"{reference.source_type}:{reference.source_id}#{chunk.index}"


def _encode_extra(extra: Mapping[str, str], where: str) -> str:
    """Serialize the whole `extra` mapping as one canonical JSON envelope.

    `SourceMetadata.extra` is annotated `Mapping[str, str]` and the established
    convention is that callers pre-serialize nested data themselves, so string
    values round-trip exactly — including a value that is itself a JSON
    document. `SourceMetadata.__post_init__` validates only `reference`, so the
    annotation is unenforced at runtime; the guards below are defensive, and
    exist so a violating caller gets a contextual error rather than a silent
    `str()` coercion.
    """
    if not isinstance(extra, Mapping):
        raise ChromaStoreError(f"{where}: metadata.extra must be a mapping, got {extra!r}")
    for key in extra:
        if not isinstance(key, str):
            raise ChromaStoreError(
                f"{where}: metadata.extra keys must be strings, got {key!r}"
            )
    try:
        return _canonical_json(dict(extra))
    except (TypeError, ValueError) as exc:
        raise ChromaStoreError(
            f"{where}: metadata.extra is not JSON-serializable: {exc}"
        ) from exc


def _encode_metadata(chunk: DocumentChunk) -> dict[str, str | int]:
    """Flatten a chunk's provenance into Chroma's scalar metadata namespace.

    Optional fields are omitted rather than written as None, because Chroma
    rejects None metadata values. `SourceMetadata.__post_init__` does not check
    `title`, `provider`, or `content_format`, so the adapter validates them here
    rather than trusting the domain to have done it.
    """
    where = _describe(chunk)
    metadata = chunk.metadata
    encoded: dict[str, str | int] = {
        _KEY_SOURCE_ID: metadata.reference.source_id,
        _KEY_SOURCE_TYPE: str(metadata.reference.source_type),
        _KEY_CHUNK_INDEX: chunk.index,
        _KEY_EXTRA_JSON: _encode_extra(metadata.extra, where),
    }
    for key, value in (
        (_KEY_TITLE, metadata.title),
        (_KEY_PROVIDER, metadata.provider),
        (_KEY_CONTENT_FORMAT, metadata.content_format),
    ):
        if value is None:
            continue
        if not isinstance(value, str):
            raise ChromaStoreError(f"{where}: metadata.{key} must be a string, got {value!r}")
        encoded[key] = value
    return encoded


def _decode_extra(raw: object, record_id: str) -> Mapping[str, str]:
    """Rebuild the `extra` mapping from its JSON envelope.

    A missing envelope means an empty mapping. Anything present but unparseable,
    or parsing to something other than an object, is corrupt persisted data and
    must not be silently downgraded to an empty default.
    """
    if raw is None:
        return {}
    if not isinstance(raw, str):
        raise ChromaStoreError(
            f"record {record_id}: {_KEY_EXTRA_JSON} must be a string, got {raw!r}"
        )
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChromaStoreError(
            f"record {record_id}: {_KEY_EXTRA_JSON} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise ChromaStoreError(
            f"record {record_id}: {_KEY_EXTRA_JSON} must decode to an object, "
            f"got {decoded!r}"
        )
    for key, value in decoded.items():
        if not isinstance(value, str):
            raise ChromaStoreError(
                f"record {record_id}: {_KEY_EXTRA_JSON}[{key!r}] must be a string, "
                f"got {value!r}"
            )
    return decoded


def _require_str(metadata: Mapping[str, object], key: str, record_id: str) -> str:
    """Read a required non-blank scalar field."""
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ChromaStoreError(
            f"record {record_id}: {key} must be a non-empty string, got {value!r}"
        )
    return value


def _decode_optional_str(
    metadata: Mapping[str, object], key: str, record_id: str
) -> str | None:
    """Read an optional scalar field; absent or None both mean None.

    `SourceMetadata.__post_init__` validates only `reference`, so a corrupt
    persisted value here would otherwise reach the domain unchecked (§7).
    """
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChromaStoreError(
            f"record {record_id}: {key} must be a string, got {value!r}"
        )
    return value


def _decode_chunk(
    record_id: str, document: object, metadata: object
) -> DocumentChunk:
    """Rebuild a DocumentChunk from one persisted record.

    Built in the order SourceReference -> SourceMetadata -> DocumentChunk so each
    domain type's own validation runs on the way out. That is a weaker guard than
    it looks, since SourceMetadata checks only `reference`; the optional fields
    and `extra` are therefore validated here. Every failure — vendor, stdlib, or
    domain — leaves this function as a ChromaStoreError naming the record.
    """
    if not isinstance(metadata, Mapping):
        raise ChromaStoreError(
            f"record {record_id}: metadata must be a mapping, got {metadata!r}"
        )
    if not isinstance(document, str):
        raise ChromaStoreError(
            f"record {record_id}: document must be a string, got {document!r}"
        )
    raw_type = _require_str(metadata, _KEY_SOURCE_TYPE, record_id)
    index = metadata.get(_KEY_CHUNK_INDEX)
    if isinstance(index, bool) or not isinstance(index, int):
        raise ChromaStoreError(
            f"record {record_id}: {_KEY_CHUNK_INDEX} must be an integer, got {index!r}"
        )
    try:
        return DocumentChunk(
            metadata=SourceMetadata(
                reference=SourceReference(
                    source_id=_require_str(metadata, _KEY_SOURCE_ID, record_id),
                    source_type=raw_type,
                ),
                title=_decode_optional_str(metadata, _KEY_TITLE, record_id),
                provider=_decode_optional_str(metadata, _KEY_PROVIDER, record_id),
                content_format=_decode_optional_str(
                    metadata, _KEY_CONTENT_FORMAT, record_id
                ),
                extra=_decode_extra(metadata.get(_KEY_EXTRA_JSON), record_id),
            ),
            index=index,
            content=document,
        )
    except DomainValidationError as exc:
        raise ChromaStoreError(f"record {record_id}: {exc}") from exc


def _decode_scored_chunk(
    record_id: str, document: object, metadata: object, distance: object
) -> ScoredChunk:
    """Pair a decoded chunk with its cosine similarity.

    Chroma cosine distance lies in [0.0, 2.0], so `1.0 - distance` lies in
    [-1.0, 1.0]. Negative scores are legitimate for opposing vectors and are
    never clamped (§9). A non-finite distance fails ScoredChunk's own validation
    and surfaces as a ChromaStoreError.
    """
    if isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise ChromaStoreError(
            f"record {record_id}: distance must be a number, got {distance!r}"
        )
    chunk = _decode_chunk(record_id, document, metadata)
    try:
        return ScoredChunk(chunk=chunk, score=1.0 - float(distance))
    except DomainValidationError as exc:
        raise ChromaStoreError(f"record {record_id}: {exc}") from exc


def _validate_vector(vector: object, where: str) -> list[float]:
    """Require a non-empty, numeric, finite, boolean-free vector.

    `EmbeddedChunk` already rejects empty and non-numeric vectors, but it does
    not reject NaN or infinity — Chroma would store those happily and every
    later distance involving the record would be meaningless. Booleans are
    rejected explicitly because `bool` subclasses `int` and would otherwise
    slip through the numeric check.
    """
    if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
        raise ChromaStoreError(f"{where}: vector must be a sequence, got {vector!r}")
    if not vector:
        raise ChromaStoreError(f"{where}: vector must be non-empty")
    values: list[float] = []
    for position, item in enumerate(vector):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ChromaStoreError(
                f"{where}: vector[{position}] must be a number, got {item!r}"
            )
        if not isfinite(item):
            raise ChromaStoreError(
                f"{where}: vector[{position}] must be finite, got {item!r}"
            )
        values.append(float(item))
    return values


def _first_row(result: Mapping[str, object], key: str) -> list[object]:
    """Pull one query's row out of Chroma's batched result shape.

    `query` takes a list of query vectors and answers with one row per query.
    This adapter always sends exactly one, so exactly one row must come back;
    anything else means the vendor contract changed underneath us.
    """
    rows = result.get(key)
    if rows is None:
        raise ChromaStoreError(f"query result is missing {key!r}")
    if not isinstance(rows, Sequence) or len(rows) != 1:
        raise ChromaStoreError(
            f"query result {key!r} must hold exactly one row, got {rows!r}"
        )
    row = rows[0]
    if not isinstance(row, Sequence):
        raise ChromaStoreError(
            f"query result {key!r} row must be a sequence, got {row!r}"
        )
    return list(row)


def _decode_results(result: Mapping[str, object]) -> tuple[ScoredChunk, ...]:
    """Rebuild ScoredChunk values from one query's results, nearest first.

    Chroma returns parallel rows and its contract is that they align. That is
    checked rather than trusted: a length mismatch would silently pair a
    document with another record's metadata, which is worse than an error.
    """
    ids = _first_row(result, "ids")
    documents = _first_row(result, "documents")
    metadatas = _first_row(result, "metadatas")
    distances = _first_row(result, "distances")
    if len({len(ids), len(documents), len(metadatas), len(distances)}) != 1:
        raise ChromaStoreError(
            "query result rows have mismatched lengths: "
            f"ids={len(ids)}, documents={len(documents)}, "
            f"metadatas={len(metadatas)}, distances={len(distances)}"
        )
    scored: list[ScoredChunk] = []
    for record_id, document, metadata, distance in zip(
        ids, documents, metadatas, distances, strict=True
    ):
        if document is None:
            raise ChromaStoreError(f"record {record_id}: document is missing")
        if metadata is None:
            raise ChromaStoreError(f"record {record_id}: metadata is missing")
        if distance is None:
            raise ChromaStoreError(f"record {record_id}: distance is missing")
        scored.append(
            _decode_scored_chunk(str(record_id), document, metadata, distance)
        )
    return tuple(scored)


def _validate_collection_name(name: str) -> None:
    """Apply Chroma's naming rules before the vendor sees the name.

    chromadb 1.5.9 rejects names under 3 characters, names containing spaces or
    non-ASCII, names not starting and ending alphanumeric, names containing
    '..', and IPv4-looking names. It does NOT enforce the 63-character ceiling
    its own `check_index_name` docstring advertises — 128 characters is accepted
    — so the ceiling is enforced here.
    """
    if not isinstance(name, str):
        raise ChromaStoreError(f"collection name must be a string, got {name!r}")
    if not _MIN_NAME_LENGTH <= len(name) <= _MAX_NAME_LENGTH:
        raise ChromaStoreError(
            f"collection name must be {_MIN_NAME_LENGTH}-{_MAX_NAME_LENGTH} "
            f"characters, got {len(name)}: {name!r}"
        )
    if not _NAME_PATTERN.fullmatch(name):
        raise ChromaStoreError(
            "collection name must start and end with an alphanumeric character "
            "and otherwise contain only ASCII letters, digits, '.', '_' or '-', "
            f"got {name!r}"
        )
    if ".." in name:
        raise ChromaStoreError(f"collection name must not contain '..', got {name!r}")
    if _IPV4_PATTERN.fullmatch(name):
        raise ChromaStoreError(
            f"collection name must not be an IPv4 address, got {name!r}"
        )


def _require_cosine(collection: Collection, name: str) -> None:
    """Reject an existing collection built with a different distance space.

    chromadb 1.5.9 ignores the `configuration` argument when the collection
    already exists: asking for cosine against a stored l2 collection returns the
    l2 collection silently, and every score would be wrong. The stored space
    reads from `configuration_json`; `collection.metadata` is None in 1.5.9 and
    cannot be used for this.
    """
    hnsw = (collection.configuration_json or {}).get("hnsw") or {}
    space = hnsw.get("space")
    if space != _COSINE:
        raise ChromaStoreError(
            f"collection {name!r} uses distance space {space!r}, expected "
            f"{_COSINE!r}. Chroma cannot change it in place; choose a different "
            "CHROMA_COLLECTION or delete the existing store."
        )


class ChromaVectorStore:
    """Persistent Chroma adapter behind the `VectorStore` port.

    Stale chunks are reconcilable. Record IDs derive from
    `(source_type, source_id, chunk_index)`, so re-ingesting a document whose
    content now chunks into fewer pieces would leave the higher-index records
    from the previous run behind. `delete_source` removes them: a caller that
    deletes a source before upserting its replacement converges on exactly the
    new chunk set. The delete/upsert pair is not atomic, so a storage failure
    between the two can leave one source absent until the next successful run.

    One writer at a time; concurrent writes from multiple processes are out of
    scope. Repeated construction on the same path within one process reopens the
    same collection, which sequential Streamlit reruns rely on.
    """

    def __init__(self, config: ChromaSettings) -> None:
        _validate_collection_name(config.collection)
        try:
            config.persist_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ChromaStoreError(
                f"could not create persistence directory {config.persist_path}: {exc}"
            ) from exc
        try:
            self._client = chromadb.PersistentClient(
                path=str(config.persist_path),
                settings=_client_settings(),
            )
            collection = self._client.get_or_create_collection(
                name=config.collection,
                configuration={"hnsw": {"space": _COSINE}},
                # 1.5.9 defaults this to a live DefaultEmbeddingFunction
                # instance, not a sentinel, so None must be passed explicitly.
                embedding_function=None,
            )
        except (ChromaError, ValueError) as exc:
            raise ChromaStoreError(
                f"could not open Chroma collection {config.collection!r} at "
                f"{config.persist_path}: {exc}"
            ) from exc
        _require_cosine(collection, config.collection)
        self._collection = collection

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        """Insert or replace embedded chunks. See `domain.ports.VectorStore`.

        The entire batch is validated before anything is written, so a bad item
        cannot leave a half-applied batch behind. The write itself carries no
        such guarantee: chromadb 1.5.9 documents no atomicity for `upsert`, so a
        failure inside the vendor call may leave some records applied.
        """
        if not embedded:
            return
        ids: list[str] = []
        vectors: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, str | int]] = []
        seen: dict[str, str] = {}
        dimension: int | None = None
        for position, item in enumerate(embedded):
            if not isinstance(item, EmbeddedChunk):
                raise ChromaStoreError(
                    f"item {position} must be an EmbeddedChunk, got {item!r}"
                )
            where = _describe(item.chunk)
            vector = _validate_vector(item.vector, where)
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise ChromaStoreError(
                    f"{where}: vector has dimension {len(vector)}, but the batch "
                    f"started with dimension {dimension}"
                )
            record_id = _derive_id(item.chunk)
            if record_id in seen:
                raise ChromaStoreError(
                    f"{where}: derives the same record ID as {seen[record_id]}; a "
                    "batch must not contain two chunks with the same identity"
                )
            seen[record_id] = where
            ids.append(record_id)
            vectors.append(vector)
            documents.append(item.chunk.content)
            metadatas.append(_encode_metadata(item.chunk))
        try:
            self._collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=documents,
                metadatas=metadatas,
            )
        except (ChromaError, ValueError) as exc:
            raise ChromaStoreError(
                f"could not write {len(ids)} record(s) to collection "
                f"{self._collection.name!r}: {exc}"
            ) from exc

    def delete_source(self, reference: SourceReference) -> None:
        """Delete one complete source. See `domain.ports.VectorStore`.

        Filters on both `source_id` and `source_type`, which `_encode_metadata`
        already writes as scalar metadata, so the same identifier under another
        source type is untouched. Hashing is never reversed to find the records;
        the filter reads the metadata the adapter stored.

        A reference matching nothing is a no-op: chromadb 1.5.9 raises only when
        *no* filter at all is supplied, so a zero-match `where` deletes nothing
        without error.

        Not atomic with the `upsert` that replaces the records. The vector index
        is derived data, and a later successful re-ingest repairs a partial
        failure.

        Raises:
            ChromaStoreError: On an invalid reference or any adapter failure.
        """
        if not isinstance(reference, SourceReference):
            raise ChromaStoreError(
                f"reference must be a SourceReference, got {reference!r}"
            )
        where = {
            "$and": [
                {_KEY_SOURCE_ID: reference.source_id},
                {_KEY_SOURCE_TYPE: str(reference.source_type)},
            ]
        }
        try:
            self._collection.delete(where=where)
        except (ChromaError, ValueError) as exc:
            raise ChromaStoreError(
                f"could not delete source {reference.source_type}:"
                f"{reference.source_id} from collection "
                f"{self._collection.name!r}: {exc}"
            ) from exc

    def search(self, vector: Vector, limit: int) -> Sequence[ScoredChunk]:
        """Return the nearest chunks to `vector`. See `domain.ports.VectorStore`.

        Scores are cosine similarity in [-1.0, 1.0], nearest first, never
        clamped. chromadb 1.5.9 returns fewer results than requested without
        error or warning, so an over-large `limit` simply returns everything.
        """
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ChromaStoreError(f"limit must be an int, got {limit!r}")
        if limit <= 0:
            return ()
        query = _validate_vector(vector, "query")
        try:
            result = self._collection.query(
                query_embeddings=[query],
                n_results=limit,
                include=["documents", "metadatas", "distances"],
            )
        except (ChromaError, ValueError) as exc:
            raise ChromaStoreError(
                f"could not query collection {self._collection.name!r}: {exc}"
            ) from exc
        return _decode_results(result)
