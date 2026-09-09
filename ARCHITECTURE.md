# Architecture

Kernector is organised into layered packages so that UI frameworks cannot own
business logic and the UI stays replaceable.

## Layers

| Layer | Responsibility | May import |
|---|---|---|
| `domain/` | Entities, validation, and port protocols | Standard library only |
| `application/` | Use cases and typed request/response contracts | `domain` |
| `infrastructure/` | Concrete adapters and external integrations | `domain` and approved third-party libraries |
| `packs/` | Optional executable domain packs (tools, scoring policies) | `domain` and standard library |
| `composition/` | Settings loading, factories, and dependency injection | `application`, `domain`, `infrastructure`, and enabled `packs` (lazy) |
| `presentation/` | CLI and `presentation/http/` FastAPI adapter | `application`, `domain`, and `composition` |

`web/` (Next.js) is the interactive presentation client, not a Python
layer. It is outside the table above and talks to Kernector only over HTTP
(see [Next.js / HTTP presentation migration](#nextjs--http-presentation-migration)).

## Allowed dependency directions

```text
presentation ──> composition ──> application ──> domain
                      │              ▲                ▲
                      ├────────> infrastructure ──────┤
                      └────────> packs (lazy) ────────┘
```

Everything points inward toward `domain`. Nothing points outward. Shared core
layers (`application`, `domain`, `infrastructure`, `presentation`) must not
import `packs`; only composition activates an enabled pack.

## Rules

- `domain` imports nothing but the standard library. No LangChain, no
  OpenRouter, no Chroma, no UI frameworks, no `requests`, no `config`.
- `application` imports `domain` only. It never imports presentation UI
  frameworks, LangChain, or anything that performs I/O; it talks to the
  outside world through the port protocols in `domain/ports.py`.
- `infrastructure` implements those ports. It may import approved third-party
  libraries, but never `application`, `presentation`, or `composition`.
  Infrastructure does not import application because port protocols currently
  live in `domain/ports.py`. If that location changes later, the architecture
  rule must be reconsidered explicitly rather than silently weakened.
- `composition/` is the composition root. It may construct application services
  and infrastructure adapters and is the single place where those layers are
  joined. It may also load enabled executable packs lazily via an explicit
  allowlist; it must not import packs at module scope.
- `packs/` may import `domain` and the standard library only. Packs must not
  import `application`, `infrastructure`, `presentation`, or `composition`.
- `presentation` is the only Python layer allowed to import HTTP server
  frameworks (`fastapi`, `uvicorn`, `starlette`), and those belong under
  `presentation/http/` only. Presentation must call application behavior
  through `composition` and must not construct or import infrastructure
  adapters or packs directly. HTTPX is an HTTP **client** (legitimate in
  clients and tests); it is not a server-framework boundary.
- `web/` (Next.js) communicates only through HTTP to the Python API
  (versioned product endpoints under `/api/v1/…` and unversioned
  `GET /health`). It must never **directly import, call, configure, or
  expose** infrastructure adapters, and must never import Python packages,
  connect to Chroma, call embedding or LLM providers, use document
  extractors, import packs, reach into composition, or otherwise access
  Python internals. Infrastructure may still run **indirectly** via
  `web/ → HTTP → presentation/http/ → composition → application ports →
  injected infrastructure adapters`.

## Composition root

`composition/container.py` wires concrete infrastructure implementations into
application services. Presentation is not the composition root.

## Next.js / HTTP presentation migration

See [ADR 0002](docs/adr/0002-nextjs-presentation-migration.md) for the full
decision record. Streamlit retirement is recorded in
[ADR 0004](docs/adr/0004-retire-streamlit-presentation.md). Next.js UI chrome
follows the Instrument panel identity in
[ADR 0003](docs/adr/0003-nextjs-instrument-panel-visual-identity.md). The
client-facing runtime contract (`GET /api/v1/settings`) is recorded in
[ADR 0005](docs/adr/0005-consolidate-runtime-contract-on-settings.md). Target flow:

```text
web/ (Next.js) ──HTTP──> presentation/http/ (FastAPI)
                              │
                              ▼
                         composition → application → domain
                                         ▲
                                   infrastructure
```

Next.js is the sole interactive UI; it reaches composition only through the
FastAPI HTTP adapter. FastAPI-published OpenAPI is the TypeScript contract
source of truth. Within `/api/v1`, only backward-compatible additive changes are
allowed; removals, renames, required-field additions, type or semantic
changes, and incompatible Problem Details changes require `/api/v2`
(deprecated operations stay marked in OpenAPI until a future major version).
[ADR 0005](docs/adr/0005-consolidate-runtime-contract-on-settings.md) records
an intentional exception that consolidates runtime bootstrap onto
`/api/v1/settings` and retires `/api/v1/capabilities`.
`web/` uses **`npm`** (`package-lock.json`, `npm ci`, and Node-version pinning
land in [#126](https://github.com/mahmoudazaid/Kernector/issues/126)). HTTP
failures use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) Problem
Details (`application/problem+json`). After `#125`,
[#126](https://github.com/mahmoudazaid/Kernector/issues/126) (shell) and
[#81](https://github.com/mahmoudazaid/Kernector/issues/81) (HTTP adapter +
layer-boundary / error tests) may proceed in parallel;
[#127](https://github.com/mahmoudazaid/Kernector/issues/127) owns the typed
client and local contract-drift check (needs both `#126` and `#81`); run
`npm run api:check` from `web/` (requires `uv`).
Dual-stack PR CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml),
[#128](https://github.com/mahmoudazaid/Kernector/issues/128)) runs that drift
check alongside Python and Next foundation jobs.

### Client session state (`web/`)

The active chat turn lives in browser storage under
`kernector:active-session:v1` (`web/lib/session/active-session.ts`, owned by
[#14](https://github.com/mahmoudazaid/Kernector/issues/14)): composer **draft**
plus **messages** (citations / tool outcomes carried opaquely). The store is
**domain-neutral** — shared presentation never interprets pack payloads, the
same rule as `AskResponse.tool_outputs`. Compare / Story (or any pack) session
state is **pack-presentation-owned** and must use a separate key prefix
(`kernector:pack:…`), never a field on the shared session. Legacy
`kernector:chat-messages:v1` (#235) is a write-through mirror and a read
fallback when the session key is absent or unusable. Runtime settings stay on
`kernector:runtime-settings:v1` and must not clear session keys.

## Knowledge foundation

Kernector’s reusable core is **domain-agnostic**. Business vocabulary lives in
optional packs; provider-specific ingestion lives in replaceable connectors.
See [ADR 0001](docs/adr/0001-domain-agnostic-knowledge-foundation.md).

### Generic core pipeline

Normalized knowledge enters as `SourceDocument`, then follows a shared path:
chunk → embed → vector store → retrieve (with provenance). Domain and
application layers stay origin-agnostic; they do not model tickets, Jira, or
other provider types as permanent core entities.

### Knowledge connectors

`KnowledgeConnector` (`domain/ports.py`) is the replaceable adapter port:
`list_documents()` returns provider-neutral `ConnectorDocument` values, and
`fetch_document()` returns a `SourceDocument`. Google Drive is the first
implemented connector (`infrastructure/connectors/google_drive.py`).

Drive failures map to a small domain taxonomy: `ConnectorAuthError` for
rejected credentials or permissions, `ConnectorUnavailableError` for throttling
and transport outages, and `ConnectorError` for other adapter failures.
Exception messages are fixed; raw Google bodies stay on `__cause__` only.

Presentation exposes HTTP status, user OAuth, and sync for this connector:
`GET /api/v1/connectors/google-drive` (SA flags plus OAuth connection metadata),
`GET /api/v1/connectors/google-drive/oauth/start` (CSRF state, 302 to Google, or
back to the Hub with `drive=unconfigured` when the OAuth client is missing),
`GET /api/v1/connectors/google-drive/oauth/callback` (code exchange, 302 to the
Hub with a non-sensitive `drive=` result),
`POST /api/v1/connectors/google-drive/sync` (user grant only), and
`DELETE /api/v1/connectors/google-drive` (revoke + delete the grant). Knowledge
Hub (`GoogleDrivePanel` inside `DocumentsPanel`) starts OAuth via the backend
start URL; it never stores tokens. The CLI
(`presentation.cli.sync_google_drive`) remains on the service-account path. The adapter reuses
`UploadedFileExtractor` for TXT/Markdown/PDF bytes, then overwrites metadata so
`provider` is `google_drive` rather than `upload`. Synchronization compares
Drive `version` (checksum fallback only when version is missing) to
`CatalogDocument.revision` and skips unchanged `READY` rows. Remote deletion
reconciliation and connector config editing are **not** implemented.
Concurrent HTTP syncs are unguarded server-side: the client `busy` flag covers
one tab, but two tabs or a direct `curl` can run at once.

### Optional domain packs

Kernector distinguishes **source kinds** from **domain packs**:

- **Source kind** answers “where did this evidence come from?” — Story, test,
  Confluence, SRS, OpenAPI, code, upload, or another connector. Provenance stays
  on generic `SourceReference.source_type` (opaque string) in the shared domain.
- **Domain pack** answers “what business interpretation should be applied?” —
  for example software-delivery risk scoring.

**Content packs** supply example knowledge and prompts
(`data/knowledge/packs/…`, `prompts/packs/…`). **Story Intelligence** remains
the first content/prompt example. Pack metadata fields (for example SDLC-shaped
`doc_type` or `severity`) are example metadata, not platform requirements.
Task-prompt packs are optional: the app starts and General mode works with zero
enabled prompt packs.

**Executable packs** under `packs/` contribute domain tools. The first is
`packs/software_delivery/` with tool `software_delivery.risk_score`. Enable via
`DOMAIN_TOOL_PACKS=software-delivery` (CSV; default empty). Composition loads
packs through an explicit allowlist manifest and `importlib` only for configured
IDs — a disabled pack is neither imported nor registered.

#### Multi-source tool flow

```text
connector/upload → SourceDocument → chunks/index
       → authorized cross-source retrieval → evidence bundle
       → optional domain tool (e.g. software_delivery.risk_score)
       → cited / structured result
```

Chat-time tool selection shares one chat surface with grounded RAG.
A General-mode query is matched by the pack intent policy:

- explicit generate/risk phrasing → evidence bundle → ordered tool chain
  through the opaque ``InvokeTool`` boundary → ``AskResponse`` with opaque
  ``tool_outputs`` and citations from the raw hits
- anything else → grounded RAG via ``AskKnowledge``

One domain tool consumes a multi-source evidence bundle. A new source kind does
not require a new risk tool or shared-core contract change. Absence-based
policies (for example missing acceptance criteria) apply only when evidence is
marked complete; chunk-level evidence may still contribute positive signals.

The Next.js **Software Delivery tool-result renderers** (#161) expose typed
composition views — risk score with factor citations, structured test cases,
and Markdown preview. Live chat turns feed them through the #178
projection adapter (``project_software_delivery_run_view``), not by parsing
opaque ``AskResponse.tool_outputs``. They are absent when no typed view was
projected (RAG / non-pack turns). There is no standalone tool-run
form: the only path that retrieves and orchestrates is the chat-time one
described below.

``AskResponse.tool_outputs`` remains ``Sequence[InvokeToolResponse]`` — opaque
tool name plus opaque result string. Generic ``InvokeTool``, ``AskResponse``,
and shared presentation code never interpret pack payloads. Presentation views
(``SoftwareDeliveryRunView``, ``ToolCallView``, etc.) are **not** stored on
``AskResponse``.

The generic ``ToolCallView`` envelope carries tool name, success/failure
status, and an explicitly authored summary (≤120 characters) built from typed
metadata such as score or generated-case count — never from
``InvokeToolResponse.result`` or truncated opaque payloads. Raw tool payloads
are never stored, exposed, or rendered. Shared presentation code stays
pack-agnostic; Software Delivery renderers live in `ToolRunBlock`
(`web/components/chat/ChatPanel.tsx`), which consumes only the typed projection
and never imports pack-named modules.
``AskResponse.tool_outputs`` is never populated by ``AskKnowledge`` itself: the
application layer may not import ``packs``, so the vocabulary that recognises a
tool request cannot live there.

#### Chat-time tool selection (#170)

``ToolAugmentedAsk`` (``composition/tool_augmented_ask.py``) wraps
``AskKnowledge`` and asks the enabled pack's deterministic policy —
``select_chat_intent`` in ``packs/software_delivery/chat_intent.py`` — which
workflow, if any, a query names. **Selection runs only when no task prompt is
set** (``AskRequest.prompt_key is None`` — the General chat path). Any non-empty
``prompt_key`` delegates the original request, history, and generation settings
unchanged to ``AskKnowledge`` — routing never moves into the Next.js UI.
Unmatched General queries are delegated to the grounded path verbatim, so
ordinary chat is unchanged and no tool runs speculatively.

Matched intents are either a generate/risk tool chain or neither. Generation
wins over risk-only.

The policy is **explicit-request matching, not a classifier**. Test generation
requires a same-clause creation verb (``create``, ``generate``, ``write``,
``produce``, ``draft``, ``build``) bound directly to a test artifact, with only
optional articles, adjectives, or style modifiers between them —
``gherkin``, ``cucumber``, ``feature file``, ``test plan``, or ``test cases``
alone are not sufficient, and distant verb∩artifact co-occurrence is ignored.
Risk routing accepts explicit score/assessment requests (for example
``assess/score/evaluate the risk``, ``what is the risk score for <target>``,
``how risky is <target>``) and rejects conceptual or read-only questions.
Scoped negations cancel only when they govern the matched action in the same
clause (``Do not create test cases``, ``Never generate tests``, ``Do not assess
the risk``). Constraint wording after a match (``Create test cases that do not
require admin access``) and negation in another clause (``Create tests; never
use production credentials``) do not cancel. Mixed requests keep the
non-negated intent (``Do not generate tests; assess the risk for AUTH-101``
selects risk-only). How-to forms and read-only transforms
(``Create a summary/list of the existing test cases``) never invoke tools. Determinism is the point: a chat-time tool
call is a side effect, and an explicit table is reproducible, testable offline,
and narrow in the safe direction — an unmatched query simply stays on the
grounded path. Vocabulary stays in the pack because "test cases" and "risk
score" are business terms; composition reaches the policy through
``registration.build_chat_intent_selector`` and ``importlib``, never at module
scope.

A matched turn runs through ``PackSoftwareDeliveryChat``
(``composition/software_delivery_chat.py``): filter-less cross-source retrieval
with the relevance threshold applied in composition → ``require_evidence`` →
evidence bundle → ``OrchestrateSoftwareDelivery`` via the opaque tool boundary,
wrapped in a ``ToolCallRecorder`` that keeps one ``InvokeToolResponse`` per
successful call. The reply is composed deterministically from the tools' typed
results — the export step's Markdown for generated cases, the risk step's score
band and rationale — never from a second model call. The same typed outcomes are
projected into ``SoftwareDeliveryRunView`` on ``ToolRunOutcome.run_view``
(#178); that view is **not** placed on ``AskResponse``.

Two properties are worth naming because they are easy to lose:

- **Input safety still applies.** A tool turn skips ``AskKnowledge``, but it
  retrieves through ``RewriteAndRetrieveKnowledge``, which applies
  ``reject_unsafe_query`` and the length cap before returning hits — and hits
  are required before any tool is invoked.
- **Citations come from the raw hits**, not from the evidence bundle, which
  merges chunks by ``(source_type, source_id)`` and loses ``chunk_index``.
  Row-level provenance survives only outside that merge.

Next.js chat surfaces a tool turn in this order: reply → citations → opaque
**Tools used** → #161 projected panels (when a view is present) → **Run
details**. ``ToolAugmentedAsk.consume_tool_run_view`` (forwarded by
``CorrelatedAsk``) hands the typed view beside — not inside — ``AskResponse``
to the HTTP chat mapping; the Next.js chat UI renders projected results without
importing pack-named modules or ``packs``.

#### Tool invocation boundary (#92 vs #95 vs #161 vs #170 vs #178)

- **#92** — pack-local contracts and scoring; generic ``ToolRegistry`` + single-tool
  ``InvokeTool`` that treats arguments and results as opaque strings.
- **#95** — orchestration over a retrieved evidence bundle (delivered).
- **#161** — presentation-only renderers and the generic ``ToolCallView`` envelope;
  testable with fixtures.
- **#170** — chat intent → retrieve/orchestrate → populate
  ``AskResponse.tool_outputs`` with opaque ``InvokeToolResponse`` entries
  (delivered).
- **#178** — composition projects typed pack outcomes into
  ``SoftwareDeliveryRunView`` on ``ToolRunOutcome.run_view``; Next.js chat
  renders #161 panels from the projected view without putting views on
  ``AskResponse`` (delivered).

### Grounded ask: system policy vs optional task prompts

Chat over ingested documents is orchestrated by `AskKnowledge`. The Next.js
chat UI is **intent-first**: there is no Mode selector and no preselected
workflow form. Ordinary chat turns use General grounded chat
(`AskRequest.prompt_key` unset); composition routes explicit Software Delivery
intents (test generation, risk) when the pack is enabled. `PromptRepository`
and `AskRequest.prompt_key` remain so saved commands / role instructions (#149)
can supply optional task text later without restoring a pre-chat Mode control.

The inputs that reach the model sit in **different privilege tiers**. The tier
is decided by placement, not by wording — a rule stated in prose can be argued
with by text the model reads later, but text that never reaches the system role
cannot impersonate the policy that constrains it.

| Tier | Input | Placement |
|---|---|---|
| Platform policy | `GROUNDED_RAG_SYSTEM` (`application/grounded_rag_policy.py`) | the `system` argument, **alone** |
| Untrusted evidence | retrieved chunks with provenance | a `Message` between `BEGIN/END_RETRIEVED_CONTEXT` markers |
| Optional task instruction | `PromptVariant.system` when `AskRequest.prompt_key` is set (API / future saved commands) | a `Message` after the context |
| User input | `AskRequest.query` | the final user `Message` |

These layers stay separate end to end:

- **System policy** — grounding, provenance, trust boundaries, authorization,
  safety, citations, and uncertainty; never replaced by user text.
- **Role / saved instructions** (#149) — optional chat-invoked context; cannot
  override platform policy.
- **User intent** — free-text chat; pack intent policy may select zero or one
  allowlisted capability.
- **Retrieval context** — untrusted evidence with provenance markers.
- **Tool schemas / typed outputs** — pack-owned contracts projected at the
  composition edge; shared presentation stays pack-agnostic.

Retrieved document text is attacker-influenceable: anyone who can get a document
ingested chooses its words. A pack prompt is author-supplied but still
lower-trust than platform policy. Neither is concatenated into the system
string, which is what makes "composed with, never substituted for" a structural
property rather than a matter of string ordering.

**Defense in depth, not complete protection.** Structural placement is the
primary bound. `AskKnowledge` and `RewriteAndRetrieveKnowledge` also reject a
small set of deterministic injection patterns on user/query (and history)
inputs before retrieval or generation — see `application/input_safety.py`.
That matcher is incomplete by design: novel phrasing can slip through, and a
pass must not be treated as proof the input is safe. Packs may add stricter
literal patterns via `extra_reject_patterns` frontmatter. Retrieved chunk text
is never pattern-rejected (documents stay untrusted-by-design); instead,
`_context_message` defangs literal `BEGIN/END_RETRIEVED_CONTEXT` markers inside
attacker-authored fields so a stored document cannot close the untrusted block
early.

The policy is a module constant, so `PROMPT_PACKS` can neither hide it nor offer
it as a selectable Mode. `AskRequest.prompt_key=None` means General chat (no
task template). Next.js chat always submits General turns; optional `prompt_key`
use stays on the application contract for #149.

Generation runs through `AskService`, so the domain settings allowlist
(`domain/model_settings.py`) is applied in exactly one place.

**Insufficient evidence means no *relevant* evidence, not an empty result set.**
Retrieval is top-k by cosine similarity, so a non-empty store returns `k` chunks
for any query however unrelated. `RELEVANCE_THRESHOLD` is the floor a chunk must
clear to count as evidence; when nothing clears it, `AskKnowledge` returns a
fixed insufficient-knowledge answer with no citations and never calls the model.
The shipped default of `0.0` discards only actively dissimilar chunks — it is a
floor, not a tuned value, and the right number depends on the embedding model
and corpus.

### Replaceable connectors

Connectors normalize external payloads into `SourceDocument` before the shared
pipeline. Names only (no implementation commitment in this document):

- File upload (TXT, Markdown, PDF)
- Seed JSON corpus adapter
- Future: GitHub, Jira, Confluence, Google Drive

### Catalog adapter selection

Uploaded-document lifecycle metadata uses the `DocumentCatalog` port.
Composition selects the adapter from `DOCUMENT_CATALOG_BACKEND` (`json` or
`sql`). JSON remains the unscoped single-process default. SQL binds one
`workspace_id` per adapter instance; uniqueness is
`(workspace_id, source_type, source_id)` per
[ADR 0006](docs/adr/0006-workspace-scope-identity.md). The port stays
unscoped. Application and presentation do not branch on adapter type.

- **JSON** — `DOCUMENT_CATALOG_PATH` (default `data/catalog/uploads.json`).
  Local / single-process use. Does not require `DOCUMENT_CATALOG_WORKSPACE_ID`.
- **SQL** — `DOCUMENT_CATALOG_SQL_PATH` (default `data/catalog/catalog.sqlite`)
  and required `DOCUMENT_CATALOG_WORKSPACE_ID`. Prefer this when more than one
  process may write, or when you need transactional upserts and versioned
  schema migrations. Selecting SQL, or running JSON→SQL migration, requires an
  explicit workspace id. There is no reserved `"default"` workspace.

When `DOCUMENT_CATALOG_WORKSPACE_ID` is present under either backend,
`load_settings()` validates it (`fullmatch` `[A-Za-z0-9_-]+`, at most 64
characters, stripped). Empty or whitespace-only values are absent.

**Journal mode.** Official SQLite WAL-reset fixes are 3.51.3+, 3.50.7+ within
3.50, and 3.44.6+ within 3.44. Verified fixed builds use `PRAGMA journal_mode=WAL`.
Affected or unverified builds use rollback-journal (`DELETE`) with
`BEGIN IMMEDIATE`. WAL still requires a local filesystem and same-host
processes — not NFS, network volumes, or distributed writers across hosts.
SQL catalog startup does not refuse a journal mode.

**JSON→SQL import.**

```bash
uv run python -m presentation.cli.migrate_document_catalog
```

Requires `DOCUMENT_CATALOG_BACKEND=sql` and a valid
`DOCUMENT_CATALOG_WORKSPACE_ID`. Re-runs are idempotent. The source JSON file
is left unchanged and remains the import origin if a re-import is needed.

**Rollback.** Stop catalog writers, then restore from a SQLite-produced backup
(`Connection.backup` or `VACUUM INTO`). Do not assemble a live `.sqlite` file
together with WAL/SHM files by hand.

## Error taxonomy

Operational failures cross the port boundary as typed errors so presentation can
show user-safe messages instead of vendor bodies or tracebacks. Adapters raise
fixed, adapter-authored exception text with vendor detail only on `__cause__`.
Presentation does **not** treat that text as display-safe: adapters map
operational types to fixed category sentences (see below). The HTTP adapter under
`presentation/http/` exposes the same failures as
[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) Problem Details
(`application/problem+json`) via `problem_from_exception`.

| Exception type | HTTP status | Problem `code` | Detail source |
|---|---|---|---|
| `UploadTooLargeError` | 413 | `upload_too_large` | class-composed sentence naming the byte limit |
| `InputRejectedError` | 422 | `invalid_query` | boundary-authored message |
| `ApplicationValidationError` | 500 | `operational_error` | fixed operational sentence |
| `DomainValidationError` | 500 | `operational_error` | fixed operational sentence |
| `InsufficientEvidenceError` | 422 | `insufficient_evidence` | fixed sentence |
| `ConfigurationError` | 500 | `configuration_error` | fixed sentence |
| `ProviderError` (and subclasses) | 502 | `provider_error` | fixed provider sentence |
| `ToolFailureError` | 500 | `tool_failure` | fixed tool sentence |
| `VectorStoreError` | 500 | `store_error` | fixed operational sentence |
| `KnowledgeLoadError` / document wraps | 500 | `operational_error` | fixed operational sentence |
| other | 500 | `internal_error` | fixed internal sentence |

Client request-shape failures remain **422** via Pydantic /
`problem_from_validation_errors` (schema-authored field pointers). Plain
`ApplicationValidationError` / `DomainValidationError` that reach
`problem_from_exception` are treated as internal contract violations (same fixed
operational sentence as the presentation ``DomainValidationError`` mapping). The
`InputRejectedError` subtree is the carve-out: caller-attributable refusals map
to 4xx with boundary-authored (or class-composed) detail.

| Category | Type | Layer | Meaning |
|---|---|---|---|
| validation | `ApplicationValidationError`, `UnknownPromptError`, `UnknownDocumentError` | application | Contract / input reject |
| validation | `InputRejectedError`, `UploadTooLargeError` | application | Caller-attributable refusal (4xx) |
| outcome | `InsufficientEvidenceError` | application | Grounded use case; no retrieval hits cleared the relevance threshold |
| validation | `DomainValidationError` | domain | Domain invariant violation |
| config | `ConfigurationError` | application | Missing/invalid environment at composition |
| config | `ChatConfigError`, `OllamaConfigError`, `EmbeddingConfigError`, `QueryRewriteConfigError` | infrastructure | Adapter construction; mapped to `ConfigurationError` |
| provider | `ProviderError` | domain | LLM / embedding / rewrite runtime failure |
| provider | `QueryRewriterError` | domain | Subclass of `ProviderError` from the rewrite port |
| provider | `QueryRewriteFailure` | application | Subclass of `ProviderError` wrapping rewrite failures |
| store | `VectorStoreError` | domain | Vector-store read or write failure |
| store | `ChromaStoreError` | infrastructure | Subclass of `VectorStoreError` |
| tool | `ToolArgumentValidationError` | domain | Invalid tool arguments before execution (`DomainValidationError`) |
| tool | `ToolFailureError` | domain | Tool invocation failure after valid arguments |
| ingest / documents | `IngestFailure`, `DocumentManagementError`, `Partial*Failure` | application | Upload / catalog mutation failures |
| corpus / catalog / extract | `CorpusLoadError`, `CatalogError`, `DocumentExtractionError` (+ subclasses) | infrastructure | Adapter I/O for seed, catalog, file extract |
| composition | `KnowledgeLoadError`, `DocumentUploadError`, `DocumentOperationError`, `PartialDocumentOperationError` | composition | Presentation-facing wraps of infrastructure / adapter failures |

**Empty / below-threshold retrieval is not an error.** `AskKnowledge` returns
`AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER, citations=(), run=RunMeta(...))`
with `outcome="insufficient"` and does not call the model.

HTTP / Next.js ask mapping uses a **fixed type → message map** (shared
category sentences in `presentation/failure_messages.py`; Next.js
`classifyFailure` for wire status). Exception type alone is never treated as
proof that `str(error)` is safe. When execution starts, failures also set
sanitized `RunMeta` on the response (`request_id`, `outcome="error"`,
`error_type` only — never exception text). Pre-execute construction failures
leave `run=None`.

| Caught type | User-facing message | `drop_user_turn` |
|---|---|---|
| `ApplicationValidationError` | boundary-authored `str(error)` | yes |
| `ProviderError` (incl. `QueryRewriterError`, `QueryRewriteFailure`) | fixed provider sentence | no |
| `ToolFailureError` | fixed tool sentence | no |
| `VectorStoreError`, `DomainValidationError`, other `RuntimeError` | fixed operational sentence | no |

Technical and vendor detail may remain on `__cause__` (and in logs); it must
not reach the UI. Collapsed **Run details** in Next.js chat reads only typed
`RunMeta` fields (see README); it never parses logs.

**Raise messages never carry the rejected value.** This holds for every
exception raised under `domain/`, `application/`, `packs/`, and
`presentation/` — validation types (`DomainValidationError`,
`ApplicationValidationError`, and their pack-local subclasses),
`ToolFailureError`, and bare `ValueError` alike. A message names the field
and the expected shape only. Where the value's type is the point, name the
type (`got {type(value).__name__}`).

The rejected value itself may be printed in two cases:

1. A bound was exceeded and a *preceding branch in the same function* has
   already proven the value is an `int` or a `float`. If a single `if` fuses
   the type check and the bounds check, split it — do not print the value
   from a branch that can also fire on a wrong type.
2. A *count* of rejected items (`{len(unknown)}`) together with a display of
   the *allowed* set. A count is not the value.

Container interpolation is the same leak as `{value!r}`: a list's `__str__`
*is* its `__repr__`, so `f"{sorted(unknown)}"` is byte-identical to
`f"{sorted(unknown)!r}"` and prints every untrusted key. Name the allowed
set from a module-level `*_DISPLAY` constant instead:

```python
_ALLOWED_KEYS = frozenset({"target", "evidence"})
_ALLOWED_KEYS_DISPLAY = str(sorted(_ALLOWED_KEYS))  # hoist: source is a constant

raise Error(
    f"unknown argument keys: {len(unknown)} not in {_ALLOWED_KEYS_DISPLAY}"
)
```

The hoist is safe because the source is a frozen module constant, not caller
or model input. Do not pre-stringify an untrusted collection to satisfy the
scan.

`test/architecture/test_safe_validation_messages.py` (via `raise_scan.py`)
catches repr-equivalent forms mechanically — `{v!r}`, `{v!a}`, `{repr(v)}`,
`{sorted(x)}`, `{str(sorted(x))}`, `"%r" % v`, `"{}".format(sorted(x))`,
`str.join` of a non-constant, and the same forms on a `from` cause or
inside an exception `__init__`. Forms that still need review: plain
`{value}` / `str(v)` / `"%s" % v` / `"{}".format(v)` on a dataclass;
hoisted messages (`msg = f"...{v!r}"; raise Error(msg)`); and
class-composed messages that interpolate caller text into
`super().__init__` without a repr form the scan can see.

A line may opt out with a trailing `# noqa: raise-scan` comment, but only after
adding the module path to `_NOQA_ALLOWLIST` in
`test/architecture/test_safe_validation_messages.py` — suppressions outside that
inventory fail CI.

The scan is name-agnostic on purpose: it inspects every `raise` in the scanned
directories rather than a list of exception names. A name list exempts each
subclass added later — `packs/software_delivery/errors.py` alone defines five
`DomainValidationError` subclasses — and every indirection such as
`raise error_type(...)` where `error_type` is a parameter.

## Architecture tests

Automated AST checks under `test/architecture/` and
`test/domain/test_domain_boundaries.py` fail when a layer imports a forbidden
package, and when a `domain/`, `application/`, `packs/`, or `presentation/`
raise embeds a repr-equivalent form
(`test/architecture/test_safe_validation_messages.py`).

Those checks remain valid for today’s Python tree. FastAPI / uvicorn / starlette
may appear only under `presentation/http/**` (path-prefix exception in
`test/architecture/test_layer_boundaries.py`). The local OpenAPI
contract-drift check is owned by
[#127](https://github.com/mahmoudazaid/Kernector/issues/127)
(`cd web && npm run api:check`); dual-stack PR CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml),
[#128](https://github.com/mahmoudazaid/Kernector/issues/128)) runs the same
check. Feature-migration readiness:
[docs/migration-readiness.md](docs/migration-readiness.md).

Run only the architecture boundary tests:

```bash
uv run pytest test/architecture test/domain/test_domain_boundaries.py
```

A full suite run includes those checks:

```bash
uv run pytest
```
