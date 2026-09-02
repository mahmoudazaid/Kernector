# Knowledge seed corpora

This folder defines the **seed-corpus format** used by the JSON knowledge adapter. It is not a universal contract for GitHub, Jira, Confluence, Google Drive, file uploads, or other connectors. Future adapters may receive different source structures before mapping them into the shared Domain types.

Kernector is a **generic knowledge platform**. Domain-specific examples (such as Story Intelligence / SDLC samples) live in optional packs under `packs/` and are not platform rules.

## Layout

| Path | Role |
| ---- | ---- |
| `schema.json` | Shared JSON Schema (Draft 2020-12) for one seed document object |
| `documents.json` | Neutral default samples for generic demos and the default ingest path |
| `packs/story-intelligence/documents.json` | Optional Story Intelligence example pack (SDLC-shaped samples) |

Automated tests validate every committed corpus against `schema.json`.

Unknown fields are accepted or rejected according to the `additionalProperties` rule defined in `schema.json`.

## Authoritative format

`schema.json` is the machine-readable contract for **one seed document object**.

Seed documents are stored as a JSON array of those objects in each corpus file.

## Required fields

| Field       | Description                                        |
| ----------- | -------------------------------------------------- |
| `source_id` | Stable, unique, non-blank identifier               |
| `title`     | Human-readable document title                      |
| `doc_type`  | Free-form document category (any non-blank string) |
| `content`   | Document text used later by the ingestion pipeline |
| `status`    | Document lifecycle status                          |
| `version`   | Document version string                            |

## Optional fields

| Field         | Description                                                                |
| ------------- | -------------------------------------------------------------------------- |
| `source_name` | Human-readable name of the document’s origin                               |
| `source_url`  | HTTPS URL, internal URI, or omitted when no URI exists                     |
| `tags`        | Array of non-blank strings; keep it as an array                            |
| `severity`    | Severity value, or `null` when severity is irrelevant (example-pack only)  |
| `component`   | Product area or system component (example-pack only)                       |
| `updated_at`  | ISO 8601 date or date-time, such as `2026-08-24` or `2026-08-24T10:30:00Z` |

`severity`, `component`, and similar fields remain **optional opaque metadata**. They appear in Story Intelligence examples for realism; the platform does not require them. Arbitrary extras (for example `audience` or `region` on neutral samples) are likewise opaque and preserved by the loader.

Do not invent external provenance for original Kernector guidance.

When a document is derived from an external source, `source_name` and `source_url` must identify that source. For internal documents without a URL, use an internal URI when one exists or omit `source_url`.

## Allowed values

### `doc_type`

Any non-blank string. Neutral samples use categories such as `policy`, `faq`, and `runbook`. The Story Intelligence pack uses illustrative SDLC categories such as `openapi`, `user_story`, `bug`, `source_code`, `srs`, and `qa_guidance`. These are pack content only—not an allow-list for adapters or connectors.

### `status`

- `draft`
- `approved`
- `deprecated`

Only documents with `status: "approved"` belong in the initial retrievable seed corpora.

### `severity`

When present (typically in example packs):

- `critical`
- `high`
- `medium`
- `low`
- `info`
- `null`

Use `null` when severity is not meaningful for the document. Omit the field entirely when it does not apply.

## Example documents

### Neutral default (`documents.json`)

```json
{
  "source_id": "policy-pto-001",
  "title": "Paid time off request window",
  "doc_type": "policy",
  "content": "Employees request paid time off at least ten business days before the first day of leave, except for illness or emergency absences. Managers respond within three business days. Unused PTO may carry over up to five days into the next calendar year.",
  "status": "approved",
  "version": "1.0",
  "tags": ["hr", "leave"],
  "audience": "all-staff",
  "region": "global",
  "source_name": "People Operations handbook",
  "updated_at": "2026-08-24"
}
```

### Story Intelligence pack (`packs/story-intelligence/documents.json`)

```json
{
  "source_id": "openapi-payments-001",
  "title": "Create payment endpoint",
  "doc_type": "openapi",
  "content": "POST /payments creates a payment for a customer. The request body requires amount (positive number) and currency (ISO 4217). On success the API returns 201 with a payment_id. Validation failures return 400; unauthorized callers receive 401.",
  "status": "approved",
  "version": "1.0",
  "tags": ["payments", "api"],
  "severity": null,
  "component": "payment-service",
  "source_name": "Payments API",
  "source_url": "https://example.test/openapi.json",
  "api_version": "v1",
  "updated_at": "2026-08-24"
}
```

## Mapping to Domain types

The JSON knowledge-corpus adapter ([#117](https://github.com/mahmoudazaid/Kernector/issues/117)) maps seed records into the shared types in `domain/knowledge.py`.

| Corpus field     | Domain target                                                    |
| ---------------- | ---------------------------------------------------------------- |
| `source_id`      | `SourceReference.source_id`                                      |
| `source_type`    | Opaque non-blank string; seed corpus uses documented constant `SourceType.KNOWLEDGE_DOCUMENT` (`"knowledge_document"`). Adapters may supply other kinds without editing a closed domain enum. Existing on-disk values continue to work; no reindex required. |
| `title`          | `SourceMetadata.title`                                           |
| `content`        | `SourceDocument.content`                                         |
| Remaining fields | `SourceMetadata.extra` (lists become `{key}_json` strings)       |

The seed JSON is an on-disk input format. `SourceDocument` is the framework-independent runtime representation used by the application.

Ownership:

- Chunking: [#83](https://github.com/mahmoudazaid/Kernector/issues/83)
- JSON corpus load and normalization: [#117](https://github.com/mahmoudazaid/Kernector/issues/117)
- Ingestion orchestration: [#85](https://github.com/mahmoudazaid/Kernector/issues/85)
- Runnable ingest CLI: [#118](https://github.com/mahmoudazaid/Kernector/issues/118)
- Example pack layout: [#137](https://github.com/mahmoudazaid/Kernector/issues/137)

Architecture note: [ADR 0001 — domain-agnostic knowledge foundation](../../docs/adr/0001-domain-agnostic-knowledge-foundation.md).

Do not convert `tags` into comma-separated text in the seed format, and do not modify Domain models to mirror every seed-corpus field.

## Ingest command

Ingest every normalized record from the configured corpus (default `data/knowledge/documents.json` — the neutral samples) without branching on `doc_type`:

```bash
uv run python -m presentation.cli.ingest
```

To ingest the Story Intelligence example pack instead:

```bash
KNOWLEDGE_CORPUS_PATH=data/knowledge/packs/story-intelligence/documents.json \
  uv run python -m presentation.cli.ingest
```

### Configuration

| Variable | Role | Default |
| -------- | ---- | ------- |
| `KNOWLEDGE_CORPUS_PATH` | Path to the JSON corpus array | `data/knowledge/documents.json` |
| `CHROMA_PERSIST_PATH` | Chroma persistence directory | `data/chroma` |
| `CHROMA_COLLECTION` | Chroma collection name | `kernector_knowledge` |
| `HYBRID_SEARCH_ENABLED` | Enable BM25+vector hybrid retrieve | `false` |
| `HYBRID_ALPHA` | BM25 weight in hybrid fusion (`[0,1]`) | `0.5` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Chunking window | `500` / `50` |
| `OPENROUTER_API_KEY` | Embedding credentials | (required) |
| `OPENROUTER_BASE_URL` | Embedding API base URL | (required) |
| `OPENROUTER_EMBEDDING_MODEL` | Embedding model id | `qwen/qwen3-embedding-8b` |

Settings and corpus loading go through composition; the CLI never imports infrastructure adapters.

### Output

On success, stdout reports the authoritative counts from `IngestResponse`:

```text
accepted_documents=<count>
chunk_count=<count>
```

`accepted_documents` is `len(accepted_ids)`. The command ingests all categories in the corpus the same way.

### Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | Ingestion succeeded |
| `1` | Corpus load failure or application validation failure |
| `2` | Configuration failure (settings or embedding credentials) |

Errors are printed to stderr without a traceback.

## Filter-metadata reindex

Chunks stored before metadata-filtered retrieval ([#86](https://github.com/mahmoudazaid/Kernector/issues/86)) keep `extra` only inside `extra_json`. Filtered search against those records returns zero hits until the promoted `x:` scalars exist.

Rewrite every record's metadata in place (no re-embedding):

```bash
uv run python -m presentation.cli.reindex_filter_metadata
```

On success, stdout reports `rewritten_records=<count>`. Prefer a full corpus ingest when documents or chunk settings must also change.

| Code | Meaning |
| ---- | ------- |
| `0` | Reindex succeeded |
| `1` | Store read/rewrite failure |

Errors are printed to stderr without a traceback.

## Future source support

Future sources may include:

- Uploaded TXT or Markdown files
- PDF documents
- SRS documents
- User stories
- Contracts
- Meeting transcripts
- GitHub issues
- Jira tickets
- Confluence pages
- Google Drive documents
- Extracted text from diagrams or flowcharts

These sources do not need to follow this seed-corpus JSON format. Each source adapter will extract its content and metadata, then map them into the shared `SourceDocument` Domain type before using the common RAG pipeline.

## Related issues

Foundation:

- Chunking: [#83](https://github.com/mahmoudazaid/Kernector/issues/83)
- Chroma and vector storage: [#84](https://github.com/mahmoudazaid/Kernector/issues/84)
- Knowledge ingestion use case: [#85](https://github.com/mahmoudazaid/Kernector/issues/85)
- JSON knowledge corpus adapter: [#117](https://github.com/mahmoudazaid/Kernector/issues/117)
- Ingest CLI: [#118](https://github.com/mahmoudazaid/Kernector/issues/118)
- Metadata-filtered retrieval: [#86](https://github.com/mahmoudazaid/Kernector/issues/86)

Domain-agnostic migration ([EPIC #68](https://github.com/mahmoudazaid/Kernector/issues/68)):

- Remove `Ticket` from domain: [#132](https://github.com/mahmoudazaid/Kernector/issues/132)
- Opaque `source_type`: [#133](https://github.com/mahmoudazaid/Kernector/issues/133)
- Documents-only ingest contract: [#134](https://github.com/mahmoudazaid/Kernector/issues/134)
- Generic ask grounding: [#135](https://github.com/mahmoudazaid/Kernector/issues/135)
- Story Intelligence prompt pack: [#136](https://github.com/mahmoudazaid/Kernector/issues/136)
- Example pack layout + neutral samples: [#137](https://github.com/mahmoudazaid/Kernector/issues/137)
- This documentation: [#138](https://github.com/mahmoudazaid/Kernector/issues/138)
- Future SQL document catalog: [#131](https://github.com/mahmoudazaid/Kernector/issues/131)

ADR: [0001 — domain-agnostic knowledge foundation](../../docs/adr/0001-domain-agnostic-knowledge-foundation.md).

## Out of scope for this folder

- Embedding generation
- LangChain integration
- Streamlit or FastAPI changes
- File-upload interfaces
- GitHub, Jira, Confluence, or Google Drive adapters
- Changes to Domain entities
