# Knowledge seed corpus

Curated Story Intelligence Hub documents for later RAG, including QA guidance and story-analysis knowledge with structured metadata for filtered retrieval.

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
| `doc_type`  | Seed-corpus document category                      |
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

- `qa_guidance`
- `story_analysis`
- `acceptance_criteria`
- `defect_triage`
- `test_strategy`

These values describe the committed Story Intelligence seed corpus only. They do not define every document type that future connectors may ingest.

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
  "source_id": "si-ac-001",
  "title": "Writing testable acceptance criteria",
  "doc_type": "acceptance_criteria",
  "content": "Acceptance criteria should be specific, observable, and testable. Prefer Given/When/Then or clear outcome statements. Avoid vague words such as \"fast\" or \"user-friendly\" unless measurable thresholds are defined. Each criterion should map to at least one verification idea.",
  "status": "approved",
  "version": "1.0",
  "tags": [
    "acceptance-criteria",
    "story-quality",
    "qa"
  ],
  "severity": null,
  "component": "story-analysis",
  "source_name": "Kernector Story Intelligence guidance",
  "updated_at": "2026-08-24"
}

```

This example is original Kernector guidance, so it does not claim an external `source_url`.

## Mapping to Domain types

When the ingestion pipeline loads these records later, it will map them into the shared types in `domain/knowledge.py`.


| Corpus field     | Domain target                                                    |
| ---------------- | ---------------------------------------------------------------- |
| `source_id`      | `SourceReference.source_id` with `SourceType.KNOWLEDGE_DOCUMENT` |
| `title`          | `SourceMetadata.title`                                           |
| `content`        | `SourceDocument.content`                                         |
| Remaining fields | Candidate metadata for enrichment and filtering in #83           |


The seed JSON is an on-disk input format. `SourceDocument` is the framework-independent runtime representation used by the application.

[#83](https://github.com/mahmoudazaid/Kernector/issues/83) owns chunking, metadata enrichment, and adapter-specific conversion. Do not convert `tags` into comma-separated text in #82, and do not modify Domain models to mirror every seed-corpus field.

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

These sources do not need to follow this seed-corpus JSON format. Each source adapter will extract its content and metadata, then map them into the shared `SourceDocument` or `Ticket` Domain types before using the common RAG pipeline.

## Out of scope

- Chunking and metadata enrichment: [#83](https://github.com/mahmoudazaid/Kernector/issues/83)
- Chroma and vector storage: [#84](https://github.com/mahmoudazaid/Kernector/issues/84)
- Knowledge ingestion use case: [#85](https://github.com/mahmoudazaid/Kernector/issues/85)
- Embedding generation
- LangChain integration
- Streamlit or FastAPI changes
- File-upload interfaces
- GitHub, Jira, Confluence, or Google Drive adapters
- Changes to Domain entities

