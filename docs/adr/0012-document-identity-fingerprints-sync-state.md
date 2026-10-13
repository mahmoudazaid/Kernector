# ADR 0012: Document identity, fingerprints, and sync state

## Status

Proposed

## Context

Connector sync ([EPIC #287]) decides whether to re-ingest a listed document by
comparing one value: the provider `revision` stored on the READY catalog row
(`application/sync_connector.py`). Any revision change fetches, re-chunks, and
re-embeds the whole document:

- Google Drive bumps `version` on renames and moves, so a rename re-embeds an
  unchanged file.
- Jira and GitHub issue Markdown carry the issue-level `Updated:` timestamp in
  indexed text, so any field change (rank, sprint, watchers) changes the text.
- Nothing records the chunker settings or the embedding model, so changing
  `CHUNK_SIZE`, `CHUNK_OVERLAP`, or `OPENROUTER_EMBEDDING_MODEL` leaves old
  chunks in place for every unchanged document.

[#380] introduces fingerprints to separate content, metadata, and processing
changes. [#381], [#382], [#383], [#384], [#385] and [#386] build on the same
vocabulary. This ADR records the decisions they share so each ticket does not
invent its own.

ADR number `0011` is taken by the Project Intelligence foundation; this ADR
takes the next free number.

## Decision

### 1. Identity is never a filename, path, or hash

- A document's identity is its `SourceReference(source_id, source_type)`,
  assigned by the connector from a stable provider key (Drive file id, GitHub
  `owner/repo:path`, Jira `cloud_id/issue_key`) or by Kernector for uploads.
- File names, paths, titles, and hashes are attributes. They may change without
  changing identity, and two documents with equal hashes are still two
  documents. Rename and move identity across providers is owned by [#383] and
  [#384]; duplicate detection by [#381].

### 2. Which fingerprint is used for what

| Fingerprint | Computed from | Used to decide |
| --- | --- | --- |
| `revision` | Provider marker (Drive `version`, GitHub blob SHA, Jira `updated`) | Whether anything may have changed; equal means skip without fetching |
| `provider_content_hash` | Provider hash of raw bytes (Drive `md5Checksum`, GitHub blob SHA), declared as `ConnectorDocument.content_hash` | Whether the bytes are unchanged without fetching |
| `content_fingerprint` | `fingerprint_text`: SHA-256 of extracted text, line endings normalized to LF | Whether the indexed text is unchanged after fetching |
| `metadata_fingerprint` | `fingerprint_metadata`: SHA-256 of canonical JSON of title, provider, content format, and `extra`; timestamps excluded | Whether stored chunk metadata needs rewriting. A content-format change is the exception: chunk boundaries depend on it, so it forces a re-ingest (rule 3) |
| `processing_fingerprint` | `ProcessingProfile(chunker_version, chunk_size, chunk_overlap, embedding_model).fingerprint` | Whether stored chunks were built under the current settings |

Hashes and fingerprints are change detectors only; they never identify a
document.

### 3. Which state is persisted where

- The four fingerprints live on the `catalog_documents` row as nullable columns
  (migration `006_catalog_fingerprints.sql`). There is no new table.
- Source metadata lives on every stored chunk (Chroma metadata, mirrored into
  the BM25 index). `VectorStore.update_source_metadata` rewrites it for one
  source without embedding; chunk IDs, indexes, text, and embeddings are kept,
  and source fields absent from the new metadata are removed.
- **NULL means unknown.** A NULL stored fingerprint never compares equal to
  anything. A NULL `processing_fingerprint` is a legacy row whose profile is
  unknown; it is not treated as a profile mismatch.
- **Fingerprints are written only on success.** PENDING, FAILED, and DEGRADED
  rows keep the previous row's fingerprint fields (NULL for new documents).
  Only the final READY row, written after a successful ingest or metadata
  update, carries the current profile and the new fingerprints. A failed
  re-ingest therefore never adopts a profile.

### 4. Decision rules for an existing READY row

`P` is the current processing fingerprint.

1. Stored processing fingerprint is non-NULL and differs from `P`: fetch and
   re-ingest (`updated`), even if the revision is unchanged.
2. Stored processing fingerprint is NULL (legacy):
   - Same revision: `skipped` without fetching or embedding, then adopt `P`
     with one catalog write and log `processing_profile_adopted`. The other
     fingerprints stay NULL because nothing was fetched.
   - Changed revision: no provider-hash shortcut; fetch. The stored text
     fingerprint is NULL, so equality cannot be proven and the source is
     re-ingested (`updated`).
3. Stored processing fingerprint equals `P`:
   - Same revision: `skipped`, no fetch, no write.
   - Changed revision, both provider hashes non-NULL and equal, and the
     connector can describe metadata without fetching
     (`MetadataDescribingConnector`): rebuild metadata from the listing plus the
     previously stored chunk metadata, rewrite the vector metadata, then the
     catalog row (`metadata_updated`). The connector derives the content
     format from the listed document and must refuse to describe (raise
     `ConnectorError`) when it may differ from the stored one, for example a
     `.txt` to `.md` rename; sync also falls back to fetching when the
     described format differs from the row's.
   - Otherwise fetch and fingerprint the text. Equal text fingerprint and
     equal content format: `metadata_updated`, rewriting vector metadata only
     when the metadata fingerprint changed (or is NULL). Different or NULL
     text fingerprint, or a changed content format: re-ingest (`updated`).

Rows in any other status, and new documents, keep the existing fetch-and-ingest
path.

### 5. Metadata-only path: order, recovery, and convergence

- Vectors first, then the catalog row. No PENDING row is written.
- If the previous chunk metadata is missing, or `update_source_metadata`
  returns 0 or a count different from the row's `chunk_count`, the vector state
  is inconsistent: log it and fall back to a full re-ingest (`updated`). The
  metadata path never advances the catalog and never reports
  `metadata_updated` in that case.
- A `VectorStoreError` during the read or update gives `FAILED` and leaves the
  catalog row unchanged. Chroma restores its snapshot on write failure, so the
  READY row stays accurate.
- `DualWriteVectorStore` updates Chroma first, then BM25. A BM25 failure is
  raised as `VectorStoreError` (fail closed). The next sync converges because
  the listed revision still differs from the catalog, the Chroma rewrite is
  idempotent, and the BM25 update is retried. A restart also converges, since
  BM25 is rebuilt from Chroma at startup.
- A catalog failure after a successful vector update aborts the run like other
  catalog failures; the next run converges the same way.

### 6. Delta discovery vs incremental processing

- **Incremental processing** ([#380]): given a full listing, decide per
  document whether to skip, rewrite metadata, or re-ingest, using the rules
  above.
- **Delta discovery** ([#385]): ask the provider only for what changed since a
  durable checkpoint. It feeds the same per-document rules and does not change
  them. [#386] proves both end to end.

### 7. Duplicate and replacement policy

- Two documents with equal content fingerprints remain two identities. [#381]
  may reject or no-op an upload whose content fingerprint equals an existing
  upload, using the fingerprints stored here.
- Replacing an upload with identical text is a metadata-only change by the same
  rules. Embedding reuse across ingests for unchanged chunk text is [#382].

### 8. Embedding-model changes need a full rebuild

The Chroma collection fixes its vector dimension on the first insert, and
rejects other dimensions on both upsert and query. Ingest deletes a source
before upserting it, so after a dimension-changing model switch every
re-ingested source would be deleted, fail to upsert, and end DEGRADED with no
chunks, while every search fails. A same-dimension switch leaves the collection
mixing two vector spaces until every source is re-ingested, and legacy rows and
uploads would keep old vectors indefinitely.

The processing fingerprint detects a model change but is not a migration. The
supported procedure is a full rebuild: a fresh Chroma collection, cleared
catalog rows for the workspace (tooling in [#201]), a re-sync of every
connector, and re-uploaded documents. Chunker setting changes are safe to apply
per document through rule 1.

## Consequences

- Drive renames and moves of binary files that keep the content format, and
  metadata-only issue changes, update catalog and chunk metadata with zero
  embedding calls. A rename that changes the content format re-ingests.
- Chunker setting changes re-index exactly the READY documents built under a
  different known profile. Legacy rows adopt the current profile without
  re-embedding, as [#380] intends; operators force a re-embed with a full
  rebuild.
- The issue-level `Updated:` line leaves indexed issue text. The value remains
  available as `jira_updated_at` and `github_updated_at` metadata.
- Sync responses gain a `metadata_updated` count.

[EPIC #287]: https://github.com/mahmoudazaid/Kernector/issues/287
[#201]: https://github.com/mahmoudazaid/Kernector/issues/201
[#380]: https://github.com/mahmoudazaid/Kernector/issues/380
[#381]: https://github.com/mahmoudazaid/Kernector/issues/381
[#382]: https://github.com/mahmoudazaid/Kernector/issues/382
[#383]: https://github.com/mahmoudazaid/Kernector/issues/383
[#384]: https://github.com/mahmoudazaid/Kernector/issues/384
[#385]: https://github.com/mahmoudazaid/Kernector/issues/385
[#386]: https://github.com/mahmoudazaid/Kernector/issues/386
