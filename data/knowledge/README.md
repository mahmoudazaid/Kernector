# Knowledge seed corpus

Curated heterogeneous knowledge documents for later RAG (OpenAPI, user stories, bugs, source-code notes, SRS, QA guidance) with structured metadata for filtered retrieval.

This folder defines the **seed-corpus format only**. It is not a universal contract for GitHub, Jira, Confluence, Google Drive, file uploads, or other connectors. Future adapters may receive different source structures before mapping them into the shared Domain types.

## Authoritative format

`schema.json` is the machine-readable contract, using JSON Schema Draft 2020-12, for **one seed document object**.

Seed documents are stored in `documents.json` as a JSON array of those objects. Automated tests validate each array item against the schema.

Unknown fields are accepted or rejected according to the `additionalProperties` rule defined in `schema.json`.

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
| `severity`    | Severity value, or `null` when severity is irrelevant                      |
| `component`   | Product area or system component                                           |
| `updated_at`  | ISO 8601 date or date-time, such as `2026-08-24` or `2026-08-24T10:30:00Z` |


Do not invent external provenance for original Kernector guidance.

When a document is derived from an external source, `source_name` and `source_url` must identify that source. For internal documents without a URL, use an internal URI when one exists or omit `source_url`.

## Allowed values

### `doc_type`

Any non-blank string. The committed seed corpus uses examples such as `openapi`, `user_story`, `bug`, `source_code`, `srs`, and `qa_guidance`. These are illustrative only—not an allow-list for adapters or connectors.

### `status`

- `draft`
- `approved`
- `deprecated`

Only documents with `status: "approved"` belong in the initial retrievable seed corpus.

### `severity`

- `critical`
- `high`
- `medium`
- `low`
- `info`
- `null`

Use `null` when severity is not meaningful for the document.

## Example document

```json
{
  "source_id": "openapi-payments-001",
  "title": "Create payment endpoint",
  "doc_type": "openapi",
  "content": "POST /payments creates a payment for a customer. The request body requires amount (positive number) and currency (ISO 4217). On success the API returns 201 with a payment_id. Validation failures return 400; unauthorized callers receive 401.",
  "status": "approved",
  "version": "1.0",
  "tags": [
    "payments",
    "api"
  ],
  "severity": null,
  "component": "payment-service",
  "source_name": "Payments API",
  "source_url": "https://example.test/openapi.json",
  "api_version": "v1",
  "updated_at": "2026-08-24"
}

```

This example is derived documentation, so `source_name` and `source_url` identify the origin.

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

Do not convert `tags` into comma-separated text in the seed format, and do not modify Domain models to mirror every seed-corpus field.

## Ingest command

Ingest every normalized record from the configured corpus (default `data/knowledge/documents.json`) without branching on `doc_type`:

```bash
uv run python -m presentation.cli.ingest
```

### Configuration

| Variable | Role | Default |
| -------- | ---- | ------- |
| `KNOWLEDGE_CORPUS_PATH` | Path to the JSON corpus array | `data/knowledge/documents.json` |
| `CHROMA_PERSIST_PATH` | Chroma persistence directory | `data/chroma` |
| `CHROMA_COLLECTION` | Chroma collection name | `kernector_knowledge` |
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

- Chunking: [#83](https://github.com/mahmoudazaid/Kernector/issues/83)
- Chroma and vector storage: [#84](https://github.com/mahmoudazaid/Kernector/issues/84)
- Knowledge ingestion use case: [#85](https://github.com/mahmoudazaid/Kernector/issues/85)
- JSON knowledge corpus adapter: [#117](https://github.com/mahmoudazaid/Kernector/issues/117)
- Ingest CLI: [#118](https://github.com/mahmoudazaid/Kernector/issues/118)

## Out of scope for this folder

- Embedding generation
- LangChain integration
- Streamlit or FastAPI changes
- File-upload interfaces
- GitHub, Jira, Confluence, or Google Drive adapters
- Changes to Domain entities

