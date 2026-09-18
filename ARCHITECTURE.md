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
`fetch_document()` returns a `SourceDocument`. Implemented connectors:

- Google Drive (`infrastructure/connectors/google_drive/`) — Hub user OAuth
  plus CLI service-account sync.
- GitHub (`infrastructure/connectors/github/`) — Hub user OAuth plus CLI PAT
  sync for allowlisted repo files and optional ProjectV2 Issues.

Drive/GitHub failures map to a small domain taxonomy: `ConnectorAuthError` for
rejected credentials or permissions, `ConnectorUnavailableError` for throttling
and transport outages, and `ConnectorError` for other adapter failures.
Exception messages are fixed; raw provider bodies stay on `__cause__` only.

Presentation exposes HTTP status, user OAuth, and sync for Drive and GitHub
under `/api/v1/connectors/{google-drive|github}/…`. Knowledge Hub panels start
OAuth via the backend start URL and never store tokens. Grant JSON lives under
`data/*-oauth-*.json` (gitignored). The Drive CLI remains on the service-account
path; the GitHub CLI uses `GITHUB_TOKEN` from the environment only.

Drive synchronization compares Drive `version` to `CatalogDocument.revision`
and skips unchanged `READY` rows. Drive sync is **add/update-only** (no remote
deletion reconciliation). GitHub sync opts into hard-delete reconciliation for
`source_type=github` when the listing completes with zero `FAILED` outcomes;
incomplete listings must raise rather than return a short list. Concurrent HTTP
syncs are unguarded server-side: the client `busy` flag covers one tab, but two
tabs or a direct `curl` can run at once. Multi-instance claim is deferred (#270).
Scheduled sync and webhooks are out of scope.

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

**Executable packs** under `packs/` contribute domain tools and pack-local
workflows. The first is `packs/software_delivery/`. Its scaffolding
risk/generate/export tools are retired (#285). Google Drive export (#309) and
**Test Design** (#293) are recognized via composition ``WorkflowSignal`` probes
injected into the pack-neutral ``TurnRouter`` (#312). Incomplete intents
clarify instead of falling through to grounded RAG (#304, #310). Shared
`application/markdown.py` (#305) is a reusable deterministic CommonMark
renderer for typed documents — not an agent-callable Tool, not Drive- or
pack-specific; later export flows (for example #197) map content into its
neutral contracts. The **Test Design**
workflow (#293) is pack-local (not an agent `Tool`): after a ready
``tool_workflow`` decision, composition builds a fixed server answer and
`Start Test Design` action with a canonical `source_locator`; create then
fetches that Issue live via `LiveSourceReader`
(OAuth preflight first; no catalog/vector/RAG). Test candidate suggestion under
`packs/software_delivery/test_design/` (pack-local use case `SuggestTestCandidates`
in `suggest_tests.py`, not an agent Tool) sees only `SourceDocument` evidence,
persists candidates and coverage gaps via a namespaced versioned workspace
store, and supports edit/select/save/confirm through `ready` (coverage
selection confirmed — not detailed test-case generation; that remains #300).
Always-mounted `/api/v1/test-design/*` routes return `test_design_unavailable`
when the pack is off. Enable via
`DOMAIN_TOOL_PACKS=software-delivery`
(CSV; default empty). Composition loads packs through an explicit allowlist
manifest and `importlib` only for configured IDs — a disabled pack is neither
imported nor registered.
``SOFTWARE_DELIVERY_AGENT_LOOP`` (default ``false``) selects the LangGraph
agent on the Drive-export ``tool_workflow`` path when the flag is on. When the
flag is off, recognized Drive-export intent clarifies as ``tool_unavailable``
(never RAG for clear/partial export commands; docs/prose mentions of export
still reach grounded RAG). The deterministic ``orchestrate`` closure remains
wired for composition provenance but is **dormant from chat**: no WorkflowSignal
can become READY Drive-export without the agent loop, matching how #285 retired
the create-test-cases chat-intent path.

#### Multi-source tool flow

```text
connector/upload → SourceDocument → chunks/index
       → authorized cross-source retrieval → evidence bundle
       → optional domain tool (when registered under tools/)
       → cited / structured result
```

Chat-time routing shares one chat surface across grounded RAG, labelled
non-RAG general answers, clarification, and pack workflows (#312).
``TurnRouter`` (``application/turn_routing.py``) is the single pre-retrieval
decision boundary. Domain/application code stays pack- and LangGraph-neutral;
composition injects ``WorkflowSignal`` probes and builds handoffs/tool runs
**after** the decision.

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

#### Conversational intent router (#312)

``TurnRouter`` / ``classify_turn`` (``application/turn_routing.py``) is the
**single** pre-retrieval routing boundary. It emits a ``RoutingDecision`` with
``kind`` ∈ ``tool_workflow`` | ``clarification`` | ``grounded_answer`` |
``general_answer``. ``RunMeta.intent`` is that kind; ``routing_confidence`` is a
**fixed heuristic score** (not calibrated probability); ``ambiguous`` marks
conflicts/mixed cues; reasons are allowlisted codes only.

**Pre-routing rule:** non-empty ``AskRequest.prompt_key`` skips the router and
delegates to ``AskKnowledge`` with ``path=task_prompt``.

**Aggregation (deterministic):**

1. Conflicting workflow signals → ``clarification``
2. Any incomplete signal (recognized intent, not ready) → ``clarification``
   (never RAG; never unauthorized tools)
3. Exactly one ready signal → ``tool_workflow``
4. No signals → cue heuristics: mixed general+project → clarify; clear general →
   ``AskGeneral``; project/default → grounded RAG
5. Disabled/unavailable tools for a recognized workflow → incomplete
   (``tool_unavailable``), never RAG

**Intent vs readiness:** signals separate “user asked for this workflow” from
“required inputs exist”. Test Design is ready only with exactly one Issue
locator; Drive export is ready only with a clear export-to-Drive phrase **and**
a draft with selected titles (and agent loop enabled). Partial phrases and
missing payloads clarify (#304, #310).

**Follow-ups:** bare “yes”/short affirmatives from raw history never promote to
``tool_workflow``. Structured clarification context is stored per
``conversation_id`` (process-scoped
``InMemoryClarificationContextStore``) when a turn clarifies. The next turn
loads that context into WorkflowSignals: a Test Design follow-up that supplies
a valid Issue locator (URL, ``owner/repo#N``, or ``owner/repo/N``) becomes
``tool_workflow`` without restating the command phrase; bare numbers or “yes”
for Test Design stay on clarification (never RAG). A Drive partial-export
clarify followed by “yes”/“ok” confirms ``export_confirmation`` and becomes
``tool_workflow`` when a draft with selected titles is ready (otherwise
``missing_fields``); raw history alone still does not promote. Context is
cleared on tool_workflow, grounded, or general paths.

**AskGeneral** (``application/ask_general.py``): ``ChatModel``/``AskService``
only — no retrieve, no citations. System policy forbids project/repository
source facts; the router must not choose ``general_answer`` when project cues
are present.

Composition injects ``WorkflowSignal`` probes
(``composition/workflow_signals.py``) and builds Test Design handoff actions
**after** a ready decision. HITL / tool authorization remain separate from
intent routing. Domain/application never import LangGraph.

#### Chat-time tool execution (#170 / #309)

``ToolAugmentedAsk`` (``composition/tool_augmented_ask.py``) applies the
task-prompt pre-rule, runs ``TurnRouter``, then dispatches. Drive
``tool_workflow`` runs through ``PackSoftwareDeliveryChat`` when the agent loop
is on. Generation
wins over risk-only for any residual scaffolding doubles in unit tests.

A matched Drive turn runs through ``PackSoftwareDeliveryChat``
(``composition/software_delivery_chat.py``): filter-less cross-source retrieval
with the relevance threshold applied in composition → ``require_evidence`` →
evidence bundle → agent/orchestrate via the opaque tool boundary,
wrapped in a ``ToolCallRecorder`` that keeps one ``InvokeToolResponse`` per
successful call. The reply is composed deterministically from the tools' typed
results — the export step's Markdown for generated cases, the risk step's score
band and rationale — never from a second model call. The same typed outcomes are
projected into ``SoftwareDeliveryRunView`` on ``ToolRunOutcome.run_view``
(#178); that view is **not** placed on ``AskResponse``.

**Agent loop (#43), opt-in:** ``SOFTWARE_DELIVERY_AGENT_LOOP`` (default
**false**) swaps only the pack ``orchestrate`` callable for a LangGraph-backed
``ToolCallingAgent`` adapter (``infrastructure/agents/langgraph_tool_agent.py``)
wired through ``composition/software_delivery_agent.py``. Intent selection,
retrieve → recorder → ordered ``tool_outputs``, stop handling, and sanitized
``ToolRunFailedError`` stay on the #170 path. Domain and application must not
import LangGraph; ``langgraph`` is an infrastructure I/O package. With chat
intent always ``None`` (#285), flipping the flag has no observable effect until
a real tool and matcher land. Keep the deterministic chain as the default until
the agent path is proven.

**Short-term thread memory (#213):** when the agent loop is on, composition owns
a process-scoped ``InMemorySaver`` (``composition/short_term_memory.py``) keyed
as ``{workspace_id}:{conversation_id}`` where ``workspace_id`` comes only from
trusted server config (``DOCUMENT_CATALOG_WORKSPACE_ID``) and ``conversation_id``
is the client thread id from #246. Checkpoints are **process-local** and are
**lost on process restart**. Deleting a conversation *best-effort* clears only
that thread's checkpoint (idempotent; missing checkpoint is success); a failed
clear leaves the checkpoint until process restart. There is no workspace-wide
or global clear and no normal-UI "reset memory" control. Long-term memory is
deferred to #299. Absent ``conversation_id``, the agent stays stateless.

**HITL tool approval (#214):** allowlisted tools (currently Drive export) pause
via LangGraph ``interrupt()`` immediately before ``Tool.run``. Pending Tool
arguments stay in process-local checkpoint/ledger state; the browser sends only
``approve`` / ``reject``. The same ``InMemorySaver`` process-local limits apply:
a restart drops pending approvals and decision ledgers. Resume uses
``Command(resume=...)`` on the same ``{workspace_id}:{conversation_id}`` thread.
LangGraph stays in infrastructure; packs/domain/application stay free of it.

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

#### Tool invocation boundary (#92 vs #95 vs #161 vs #170 vs #178 vs #43)

- **#92** — pack-local contracts and scoring; generic ``ToolRegistry`` + single-tool
  ``InvokeTool`` that treats arguments and results as opaque strings.
- **#95** — orchestration over a retrieved evidence bundle (delivered).
- **#161** — presentation-only renderers and the generic ``ToolCallView`` envelope;
  testable with fixtures.
- **#170** — chat intent → retrieve/orchestrate → populate
  ``AskResponse.tool_outputs`` with opaque ``InvokeToolResponse`` entries
  (delivered; **default** orchestrate path).
- **#178** — composition projects typed pack outcomes into
  ``SoftwareDeliveryRunView`` on ``ToolRunOutcome.run_view``; Next.js chat
  renders #161 panels from the projected view without putting views on
  ``AskResponse`` (delivered).
- **#43** — optional LangGraph agent orchestrate behind
  ``SOFTWARE_DELIVERY_AGENT_LOOP`` (default off); same runner ledger and error
  taxonomy. Dormant while chat intent never matches (#285).

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
The agentic grounded path (`AskKnowledgeWithAgent` / `RetrieveKnowledgeTool`)
applies the same floor before recording citations, as does the pack retrieve
binder. The shipped default of `0.0` discards only actively dissimilar chunks —
it is a floor, not a tuned value, and the right number depends on the embedding
model and corpus.

### Replaceable connectors

Connectors normalize external payloads into `SourceDocument` before the shared
pipeline. Names only (no implementation commitment in this document):

- File upload (TXT, Markdown, PDF)
- Seed JSON corpus adapter
- Future: Jira, Confluence
- Implemented: Google Drive, GitHub

### Catalog adapter

Uploaded-document lifecycle metadata uses the `DocumentCatalog` port.
Composition wires only `SqlDocumentCatalog`, bound to one `workspace_id` per
adapter instance. Uniqueness is `(workspace_id, source_type, source_id)` per
[ADR 0006](docs/adr/0006-workspace-scope-identity.md). The port stays
unscoped. Application and presentation do not branch on adapter type.

- **SQLite path** — `DOCUMENT_CATALOG_SQL_PATH` (default
  `data/catalog/catalog.sqlite`). Blank values are stored as absent and fail at
  catalog build, not process bootstrap.
- **Workspace** — `DOCUMENT_CATALOG_WORKSPACE_ID`. There is no reserved
  `"default"` workspace. `load_settings()` stores the stripped value when
  present (blank is absent) and does not validate charset or length.
  Composition requires a valid workspace when building `SqlDocumentCatalog`
  and maps absence/malformation to `ConfigurationError`.
- **Retired keys** — Non-blank `DOCUMENT_CATALOG_BACKEND` or
  `DOCUMENT_CATALOG_PATH` fail at catalog build with `ConfigurationError`
  (not at process bootstrap). Remove them after migrating from JSON.

**Upgrading from JSON.** Before upgrading past the release that removed the
JSON adapter ([#261](https://github.com/mahmoudazaid/Kernector/issues/261)),
operators with rows in `data/catalog/uploads.json` must run the migrator on
that prior release, then remove `DOCUMENT_CATALOG_BACKEND` and
`DOCUMENT_CATALOG_PATH` before starting the upgraded build. See
[README.md](README.md) and
[ADR 0007](docs/adr/0007-retire-json-document-catalog.md).

**Journal mode.** Official SQLite WAL-reset fixes are 3.51.3+, 3.50.7+ within
3.50, and 3.44.6+ within 3.44. Verified fixed builds use `PRAGMA journal_mode=WAL`.
Affected or unverified builds use rollback-journal (`DELETE`) with
`BEGIN IMMEDIATE`. WAL still requires a local filesystem and same-host
processes — not NFS, network volumes, or distributed writers across hosts.
SQL catalog startup does not refuse a journal mode.

**Upload blob store.** Original upload bytes live under
`DOCUMENT_UPLOAD_BLOB_PATH` (default `data/uploads`) as flat files keyed by
`source_id` only — not by workspace. Preview and download
(`GET /api/v1/documents/{source_id}/content` and `/download`) resolve the
catalog row first, then read the blob. The store is last-write-wins with no
point-in-time recovery: restoring a catalog backup does not restore blobs.
Same-host concurrent writers are safe via `os.replace` plus a per-path lock.

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
| `ConfigurationBoundaryError` | 500 | `configuration_error` | fixed sentence (marker; prefer concrete subclasses) |
| `MissingProviderCredentialsError` | 500 | `missing_provider_credentials` | fixed sentence |
| `OllamaNotConfiguredError` | 409 | `ollama_unconfigured` | fixed sentence |
| `ToolRunFailedError` | 500 | `tool_failure` | fixed tool sentence |
| `ProviderAuthError` | 502 | `provider_auth_failed` | curated auth remediation |
| `ProviderCreditsError` | 502 | `provider_credits_exhausted` | curated credits remediation |
| `ProviderModelUnavailableError` | 502 | `provider_model_unavailable` | curated model remediation |
| `ProviderRateLimitError` | 502 | `provider_rate_limited` | curated rate-limit remediation |
| `ProviderTimeoutError` | 502 | `provider_timeout` | curated timeout remediation |
| `ProviderNetworkError` | 502 | `provider_network_error` | curated network remediation |
| `ProviderError` (and other subclasses) | 502 | `provider_error` | fixed provider sentence; on Software Delivery tool-run paths, `PackSoftwareDeliveryChat` re-wraps into `ToolRunFailedError` (500 `tool_failure`) so vendor text never reaches the chat bubble |
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
| config | `ConfigurationBoundaryError` | domain | Marker base for typed config failures; prefer concrete application subclasses |
| config | `ChatConfigError`, `OllamaConfigError`, `EmbeddingConfigError`, `QueryRewriteConfigError` | infrastructure | Adapter construction; mapped to `ConfigurationError` / `MissingProviderCredentialsError` / `OllamaNotConfiguredError` |
| provider | `ProviderError` | domain | LLM / embedding / rewrite runtime failure |
| provider | `ProviderAuthError`, `ProviderCreditsError`, `ProviderModelUnavailableError`, `ProviderRateLimitError`, `ProviderTimeoutError`, `ProviderNetworkError` | domain | Actionable subclasses of `ProviderError` from chat/rewrite adapters |
| provider | `QueryRewriterError` | domain | Subclass of `ProviderError` for blank/unusable rewrite content |
| provider | `QueryRewriteFailure` | application | Subclass of `ProviderError` wrapping `QueryRewriterError` |
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
leave `run=None`. Structured operation logs may use `error_type` for a
sanitized category and `exception_type` for the exception class name when both
are needed (see README observability).

| Caught type | User-facing message | `drop_user_turn` |
|---|---|---|
| `ApplicationValidationError` | boundary-authored `str(error)` | yes |
| `ProviderError` (incl. actionable subclasses, `QueryRewriterError`, `QueryRewriteFailure`) | fixed / curated provider sentence by type | no |
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
