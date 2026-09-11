# Kernector

![Kernector overview](docs/images/kernector-overview.png)

Kernector is a domain-agnostic knowledge platform built around a shared ingest and retrieval pipeline. Uploaded TXT, Markdown, and PDF files, seed JSON corpora, and the Google Drive CLI connector normalize into `SourceDocument`; the core then chunks, embeds, stores, and retrieves with provenance so answers can cite what they used. Domain vocabulary stays out of the reusable core. Optional packs supply business meaning. External provider connectors beyond Google Drive (for example Jira or Confluence) are planned, not shipped. The default seed corpus at `data/knowledge/documents.json` is neutral. Story Intelligence samples under `data/knowledge/packs/story-intelligence/` demonstrate a content pack without defining platform requirements.

Architecture and layering live in [ARCHITECTURE.md](ARCHITECTURE.md). The domain-agnostic direction is recorded in [ADR 0001](docs/adr/0001-domain-agnostic-knowledge-foundation.md). The Next.js / HTTP presentation migration is recorded in [ADR 0002](docs/adr/0002-nextjs-presentation-migration.md). The Next.js Instrument panel visual identity is recorded in [ADR 0003](docs/adr/0003-nextjs-instrument-panel-visual-identity.md). Streamlit retirement is recorded in [ADR 0004](docs/adr/0004-retire-streamlit-presentation.md). Seed format details are in [data/knowledge/README.md](data/knowledge/README.md).

## How the platform is structured

Dependency arrows point inward toward `domain`. Presentation never owns business logic; infrastructure never imports application use cases; packs never reach into composition or the Next.js UI.

![Kernector architecture](docs/images/kernector-architecture.png)

`domain/` holds entities, validation, and port protocols and imports only the standard library. `application/` implements use cases such as ingest, rewrite-and-retrieve, grounded ask, and tool invocation, speaking to the outside world only through those ports. `infrastructure/` supplies concrete adapters — Chroma vector storage, in-memory BM25, PDF/text loaders, catalog JSON, and LLM provider clients. `packs/` are optional executable modules. Today `packs/software_delivery/` registers `software_delivery.risk_score`, `software_delivery.generate_test_cases`, `software_delivery.export_test_cases_markdown`, and a deterministic chat-intent policy, without importing application or presentation code. `composition/` is the sole wiring root: it loads settings, constructs adapters, activates enabled packs through an explicit allowlist, and hands typed services to the UI. `presentation/` hosts the FastAPI HTTP adapter and CLI entrypoints; it calls through composition and must not construct infrastructure or import packs directly. The interactive UI is Next.js under `web/`, talking HTTP to FastAPI.

This split keeps the UI replaceable and prevents ticket- or SDLC-shaped types from re-entering the shared contracts. New product behavior arrives as a pack, not as a fork of the core pipeline. New source kinds arrive as additional adapters that emit `SourceDocument`. Implemented sources today are file upload, the on-disk seed JSON loader, and the Google Drive connector (HTTP status/sync plus CLI).

## Knowledge path from source to cited answer

Normalized documents follow one pipeline whether they arrived as an upload, a seed JSON row, or a Google Drive file. Additional connector payloads are planned behind the same `SourceDocument` boundary.

![Knowledge pipeline](docs/images/kernector-knowledge-pipeline.png)

After chunking and embedding, passages land in Chroma with metadata that preserves source identity. When hybrid search is enabled, the same corpus also feeds a BM25 lexical index; retrieval fuses the two channels with a configurable alpha weight (`alpha * BM25 + (1 - alpha) * vector`), then keeps provenance on each hit. Grounded ask attaches retrieved chunks as context. Next.js chat renders citations from `Citation` as source ID, source type, optional chunk index, and quote — not page or section links.

When `DOMAIN_TOOL_PACKS` includes `software-delivery` and a General-mode query explicitly requests risk scoring or test-case generation, composition routes through evidence-bundle orchestration instead of free-form generation, still citing the underlying hits. Unmatched queries stay on the ordinary RAG path — intent matching is a deterministic pack policy, not a speculative classifier.

## Next.js + FastAPI local workflow

Next.js is the interactive UI; it talks HTTP to the FastAPI adapter under
`presentation/http/`, which wires through composition. Copy
[`.env.example`](.env.example) to `.env` for Python/HTTP flags (no secrets
committed). Next public vars: [`web/.env.example`](web/.env.example) →
`web/.env.local`.

| Process | Default URL | Command |
| --- | --- | --- |
| FastAPI | `http://127.0.0.1:8000` | `HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload` |
| Next.js | `http://localhost:3000` | `cd web && npm ci && npm run dev` |

**Startup order:** start FastAPI first (browser calls need the API + CORS),
then Next.

### Run the HTTP API

FastAPI adapter under `presentation/http/`. Development CORS for the Next.js
origin is enabled only when `HTTP_DEV_CORS` is truthy
(`1` / `true` / `yes` / `on`). Optional `HTTP_CORS_ORIGINS` (default
`http://localhost:3000`; `*` is rejected). Both flags load through Settings /
`.env` like other config.

```bash
HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload
```

Or set the same keys in `.env`, then:

```bash
uv run uvicorn presentation.http.app:app --reload
```

- Unversioned ops: `GET /health`
- Runtime contract: `GET /api/v1/settings` (providers, enabled packs, shared constraints)
- Grounded chat: `POST /api/v1/chat/ask`
- Documents: `GET/POST /api/v1/documents`, `PUT/DELETE /api/v1/documents/{source_id}`
- OpenAPI: `GET /openapi.json` (also `/docs`)

See [ADR 0005](docs/adr/0005-consolidate-runtime-contract-on-settings.md) for
why `/api/v1/settings` owns client bootstrap state and why `/capabilities` was
retired.

**Dev vs production CORS:** leave `HTTP_DEV_CORS` unset/false in production
unless you intentionally set an explicit `HTTP_CORS_ORIGINS` allowlist. Never
use `*`. `NEXT_PUBLIC_*` values are baked into the Next.js build — set
`NEXT_PUBLIC_API_BASE_URL` in the build environment before `npm run build`.

### Run the Next.js web shell

The App Router foundation lives in [`web/`](web/) (Node 22+, npm). See
[`web/README.md`](web/README.md) for full details.

```bash
# API with CORS for the Next.js origin (required for Chat / Settings / Documents from the browser)
HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload

# separate terminal
cd web
npm ci
npm run dev   # http://localhost:3000
```

Public env (optional overrides in `web/.env.local`): `NEXT_PUBLIC_APP_NAME`,
`NEXT_PUBLIC_API_BASE_URL` (defaults to `http://127.0.0.1:8000`),
`NEXT_PUBLIC_SITE_URL` (defaults to `http://localhost:3000`; used as
`metadataBase` for Open Graph URLs).

With both processes up, open `/settings` for provider/model controls and `/chat`
for grounded ask (history, citations, tools-used, projected tool results). Chat
reads runtime selections from `localStorage` (`kernector:runtime-settings:v1`)
and persists the transcript under `kernector:chat-messages:v1`.

OpenAPI → TypeScript: from `web/`, `npm run api:generate`. Drift check:
`npm run api:check` (also run on PRs to `main`).

Other commands: `npm run build`, `npm run lint`, `npm run typecheck`, `npm test`.

### CI (pull requests to `main`)

Workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Reproduce
locally (no provider API keys required):

```bash
uv sync --frozen && uv run pytest

cd web
npm ci
npm run lint && npm run typecheck && npm test && npm run build
npm run api:check   # needs uv at repo root
```

### Feature-migration readiness

Before adding or retargeting a Next.js + HTTP feature, use
[docs/migration-readiness.md](docs/migration-readiness.md).

### Troubleshooting

- **Next Chat/Settings fail / CORS errors** — Ensure FastAPI is up,
  `HTTP_DEV_CORS` is truthy, and the browser origin matches `HTTP_CORS_ORIGINS`
  (default `http://localhost:3000`).
- **OpenAPI contract drift** — `cd web && npm run api:generate`, then commit
  updated `openapi/openapi.json` and `lib/api/generated/schema.d.ts`.
- **Port already in use** — Stop the other process on 8000 / 3000, or pass an
  alternate port to uvicorn / `next dev`.
- **Embedding size / Chroma mismatch** — remove the local store and retry:
  `rm -rf data/chroma`.

## Hybrid search (optional)

Retrieval defaults to vector-only (Chroma cosine). To combine BM25 with vector
scores on the product retrieve path:

```bash
export HYBRID_SEARCH_ENABLED=true
export HYBRID_ALPHA=0.5   # BM25 weight; 1=BM25 only, 0=vector only
```

When hybrid is on, `RELEVANCE_THRESHOLD` remains a **raw cosine** eligibility
floor for the vector channel (applied before normalization/fusion). Hybrid hit
scores returned to ask/tool paths are fused ranking scores in `[0, 1]`, not
absolute relevance probabilities — do not retune the threshold against those
fused values. Lexical eligibility is token-overlap BM25. Metadata filters still
apply to both sides.

The FastAPI process caches one vector store (request deps) and reuses it for
chat retrieval and document create/replace/delete so the in-memory BM25 index
stays current without re-hydrating from Chroma on every request.

## Upload and manage documents

Open Next.js `/documents` against FastAPI. Prefer a **single uvicorn worker**
when using the JSON catalog — that lock is per process. SQL is safe for
same-host processes on a local filesystem. Upload blobs
(`DOCUMENT_UPLOAD_BLOB_PATH`, default `data/uploads`) use `os.replace` plus a
per-path lock and are safe for same-host writers; still prefer one worker with
JSON.

1. Start the FastAPI + Next stack above and open **Documents**.
2. Under **Upload new**, choose one supported file: `.txt`, `.md`, `.markdown`, or `.pdf`.
3. Submit **Upload new**. The app assigns a system-managed UUID source ID (never derived from the file name). Matching filenames create separate documents.
4. Under **Uploaded documents**, select a row to inspect status, chunk count, and the diagnostic source ID.
5. Use **Preview** for an inline viewer of the original upload bytes, or **Download** to save them.
6. To overwrite content for a selected document, choose a replacement file and submit **Replace** (same source ID; old chunks are replaced). Filenames never trigger replacement by themselves.
7. To remove a document, confirm and click **Delete** (vector chunks first, then the catalog row, then the upload blob).

Upload catalog metadata defaults to JSON at `data/catalog/uploads.json`
(`DOCUMENT_CATALOG_BACKEND=json`, `DOCUMENT_CATALOG_PATH`). Use JSON for local
single-process work. Set `DOCUMENT_CATALOG_BACKEND=sql`,
`DOCUMENT_CATALOG_SQL_PATH` (default `data/catalog/catalog.sqlite`), and
`DOCUMENT_CATALOG_WORKSPACE_ID` when you need transactional writes and
versioned schema.

To copy existing JSON rows into SQL (idempotent; source JSON unchanged):

```bash
uv run python -m presentation.cli.migrate_document_catalog
```

Verified official SQLite builds (3.51.3+, 3.50.7+ within 3.50, 3.44.6+ within
3.44) use WAL; other builds use rollback-journal with `BEGIN IMMEDIATE`. WAL
needs a local filesystem and same-host processes. To roll back a SQL catalog,
stop writers and restore from a SQLite-produced backup (`VACUUM INTO` or
`Connection.backup`) — do not splice a live `.sqlite` with WAL/SHM files.
Keep the source JSON if you need to re-import.

Seed-corpus documents remain separate and do not appear in this list.

Create, replace, and delete run to completion before the UI refreshes, and the
outcome appears above the document list. A failure that left chunks or a catalog
row behind says so and names the action to retry; one that changed nothing says
only what went wrong.

If ingest fails because the store expects a different embedding size, remove the local Chroma directory and try again:

```bash
rm -rf data/chroma
```

## Sync documents from Google Drive

Google Drive has two connection strategies. Knowledge Hub uses **user OAuth**. The CLI (#196) still uses a **service account**. Do not enter Google credentials in Next.js.

### Knowledge Hub (user OAuth)

1. Enable the Google Drive API and create an OAuth **Web application** client.
2. Set the authorized redirect URI to exactly
   `http://127.0.0.1:8000/api/v1/connectors/google-drive/oauth/callback`
   (or your deployed callback URL).
3. Set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
   `GOOGLE_OAUTH_REDIRECT_URI`, and optionally `GOOGLE_OAUTH_FRONTEND_REDIRECT`
   (see [`.env.example`](.env.example)). Never commit those values.
4. Install the extra: `uv sync --extra google-drive`.
5. In Knowledge Hub, click **Connect**. Google owns account selection and consent.
6. After the callback, choose folders (recommended) or individual files, then
   **Add selection & sync**. That saves the scope and runs the first import.
   Later **Sync** refreshes only new or changed documents. **Change Drive
   selection** reopens the picker. **Disconnect** revokes the stored grant
   and leaves already indexed documents in place.

Tokens stay on the server (`GOOGLE_OAUTH_TOKEN_PATH`). The browser only sees
presentation fields (`connected`, account email, counts, selection names).
Scope is `https://www.googleapis.com/auth/drive.readonly` with offline access.
That **restricted** scope is required so a selected folder remains a durable
sync root: Kernector must list current descendants and files added later.
Google may require app verification and, when restricted-scope data is stored
or transmitted by the server, a security assessment. `drive.file` cannot
truthfully support recursive folder sync.

A selected **folder** is a durable root (recursive, add/update-only). A selected
**file** tracks that exact Drive ID. Duplicate IDs are ingested once. Identity is
the Drive file ID; renames do not create a second catalog document. Moved,
trashed, deleted, inaccessible, and unsupported items are omitted from the next
listing and are **not** deleted from the catalog. Unchanged Drive `version`
(or `md5Checksum` / `modifiedTime` fallback) values skip download, chunking,
and embedding.

### CLI (service account)

1. Create a Google Cloud service account.
2. Enable the Google Drive API for that project.
3. Download the service-account JSON key.
4. Keep that key **outside the repository**.
5. Share the target Drive folder with the service-account email (Viewer is enough).
6. Set `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` and `GOOGLE_DRIVE_FOLDER_ID`
   (see [`.env.example`](.env.example)).
7. Install the optional extra and run:

```bash
uv sync --extra google-drive
uv run python -m presentation.cli.sync_google_drive
```

Exit codes:

| Code | Meaning |
| ---: | --- |
| `0` | Every listed document was ingested or skipped |
| `1` | At least one document failed, or the run aborted operationally |
| `2` | Connector or embedding configuration is invalid |

Supported files are the same as upload: `.txt`, `.md`, `.markdown`, and text-based `.pdf`. Google Docs are exported as Markdown. Sync is **direct-child-only** (no recursive folder walk) and **add/update-only** (files missing from Drive are not deleted from the catalog). Unchanged Drive `version` values are skipped; a changed version replaces stored chunks.

## Logging and monitoring

Kernector emits structured stdlib logging for ask, rewrite/retrieve, ingest, and
tool invocation. Set the process log level with `LOG_LEVEL` (default `INFO`):

```bash
LOG_LEVEL=DEBUG HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload
```

`load_runtime_settings()` applies this at composition bootstrap.

### Correlation lifecycle

Every chat path from `build_tool_augmented_ask` is wrapped in `CorrelatedAsk`,
including when no Software Delivery pack is enabled. On each
`GroundedAsk.execute` turn:

1. Bind a `request_id` (UUID hex) via a `ContextVar`, or **reuse** an id already
   bound by an outer caller.
2. Nested ask / rewrite-retrieve / invoke-tool logs read that same id.
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
- `request_id`, `path` (`rag` | `tools` | `task_prompt`)
- `pack` (`software-delivery` on tool routes)
- `tool`, `prompt_key`, `source_type`
- `hit_count` / `chunk_count` / `source_count`
- `latency_ms`, `model`, token usage ints from `RunMeta`

String field values are normalized (control characters / newlines replaced) so
one call cannot forge additional log lines or alternate `operation` events.

**Do not expect logs to contain:** document or chunk text, prompts, secrets or
API keys, raw provider bodies, tool arguments/results, or exception *messages*
(only exception type names). Structured error fields:

- `error_type` — sanitized category when the operation maps failures that way
  (for example `judge_error` / `observation_integrity` on `judge_observe`), or
  the exception type name when no category is recorded
- `exception_type` — optional exception type name when `error_type` holds a
  category (for example `"ProviderError"`) so logs stay correlatable with reports

Workspace/tenant correlation is deferred until an authorized identity exists;
storage details such as the Chroma collection name are not logged as a
workspace id.

### Run details in Next.js chat

Each completed Ask turn (success, insufficient evidence, or operational failure)
can show collapsed **Run details**. Metadata reaches the UI only through typed
`RunMeta` on `AskResponse.run` (and the chat turn mapping) — never by parsing
log files.

When present, Run details may show:

- request ID
- outcome (`success` / `insufficient` / `error`)
- latency
- model
- token usage
- pack
- query rewritten (`yes` / `no`) — flag only, never the query text
- retrieval hit count
- citation count (one entry per citation attached to the response; same as hit count today because citations are built 1:1 from hits without deduplication)
- invoked tool **names**

Unset optional fields are omitted. The UI does **not** display prompts, queries,
retrieved chunks, document content, tool arguments/results, secrets, raw
provider responses, generation settings blobs, or exception text (including
`error_type`).

The diagrams document implemented layering and the current ingest path. Extending
Kernector means enabling packs behind composition’s allowlist, or adding adapters
that emit `SourceDocument`, without widening the shared domain with
product-specific entities.
