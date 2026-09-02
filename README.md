# Kernector

Kernector is a **domain-agnostic knowledge platform**: a shared ingest and
retrieval pipeline over `SourceDocument`, with optional domain packs and
replaceable source connectors. The default seed corpus
(`data/knowledge/documents.json`) is neutral; Story Intelligence samples live
under `data/knowledge/packs/story-intelligence/` as an example pack, not a
platform requirement.

Architecture and layering: [ARCHITECTURE.md](ARCHITECTURE.md). Domain-agnostic
direction: [ADR 0001](docs/adr/0001-domain-agnostic-knowledge-foundation.md).
Seed format details: [data/knowledge/README.md](data/knowledge/README.md).

## Run the Streamlit app

```bash
uv run streamlit run main.py
```

## Upload and manage documents

1. Start the app with the command above.
2. Under **Upload new document**, choose one supported file: `.txt`, `.md`, `.markdown`, or `.pdf`.
3. Submit **Upload new**. The app assigns a system-managed UUID source ID (never derived from the file name). Matching filenames create separate documents.
4. Under **Uploaded documents**, select a row to inspect status, chunk count, and the diagnostic source ID.
5. To overwrite content for a selected document, choose a replacement file and submit **Replace** (same source ID; old chunks are replaced). Filenames never trigger replacement by themselves.
6. To remove a document, confirm and click **Delete** (vector chunks first, then the catalog row).

Upload catalog metadata is stored at `data/catalog/uploads.json` by default (`DOCUMENT_CATALOG_PATH`). Seed-corpus documents remain separate and do not appear in this list.

Create, replace, and delete run to completion before the page refreshes, and the outcome appears above the document list on the refreshed page. A failure that left chunks or a catalog row behind says so and names the action to retry; one that changed nothing says only what went wrong.

If ingest fails because the store expects a different embedding size, remove the local Chroma directory and try again:

```bash
rm -rf data/chroma
```

## Logging and monitoring

Kernector emits structured stdlib logging for ask, rewrite/retrieve, ingest, and
tool invocation. Set the process log level with `LOG_LEVEL` (default `INFO`):

```bash
LOG_LEVEL=DEBUG uv run streamlit run main.py
```

`load_runtime_settings()` applies this at composition bootstrap.

### Correlation lifecycle

Every chat path from `build_tool_augmented_ask` is wrapped in `CorrelatedAsk`,
including when no Software Delivery pack is enabled. On each
`GroundedAsk.execute` turn:

1. Bind a `request_id` (UUID hex) via a `ContextVar`, or **reuse** an id already
   bound by an outer caller.
2. Nested ask / rewrite-retrieve / invoke-tool / analysis logs read that same id.
3. Restore the previous ContextVar binding with `reset(token)` in a `finally`
   block — never force-clear a caller’s outer context.

### Log format

Each operation emits **one single-line JSON object** (sorted keys), for example:

```json
{"hit_count":1,"latency_ms":12,"model":"test-model","operation":"ask","outcome":"success","request_id":"…","source_type":"knowledge_document","total_tokens":99}
```

Typical fields when available:

- `operation` / `outcome` (`ask`, `rewrite_retrieve`, `invoke_tool`, `ingest`, `ask_turn`)
- `outcome` values: `success`, `insufficient`, `error`, or `delegated` (router
  handed off to grounded ask; the nested `ask` event is terminal)
- `request_id`, `path` (`rag` | `tools` | `task_prompt` | `analysis`)
- `pack` (`software-delivery` on tool/analysis routes)
- `tool`, `prompt_key`, `source_type`
- `hit_count` / `chunk_count` / `source_count`
- `latency_ms`, `model`, token usage ints from `RunMeta`

String field values are normalized (control characters / newlines replaced) so
one call cannot forge additional log lines or alternate `operation` events.

**Do not expect logs to contain:** document or chunk text, prompts, secrets or
API keys, raw provider bodies, tool arguments/results, or exception *messages*
(only exception type names such as `"error_type":"ProviderError"`).

Workspace/tenant correlation is deferred until an authorized identity exists;
storage details such as the Chroma collection name are not logged as a
workspace id.
