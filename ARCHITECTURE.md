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
| `presentation/` | Streamlit and future UI adapters | `application`, `domain`, and `composition` |

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
  OpenRouter, no Chroma, no Streamlit, no `requests`, no `config`.
- `application` imports `domain` only. It never imports Streamlit, LangChain,
  or anything that performs I/O; it talks to the outside world through the
  port protocols in `domain/ports.py`.
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
- `presentation` is the only layer allowed to import Streamlit. It must call
  application behavior through `composition` and must not construct or import
  infrastructure adapters or packs directly.

## Composition root

`composition/container.py` wires concrete infrastructure implementations into
application services. Presentation is not the composition root.

## Knowledge foundation

Kernector’s reusable core is **domain-agnostic**. Business vocabulary lives in
optional packs; provider-specific ingestion lives in replaceable connectors.
See [ADR 0001](docs/adr/0001-domain-agnostic-knowledge-foundation.md).

### Generic core pipeline

Normalized knowledge enters as `SourceDocument`, then follows a shared path:
chunk → embed → vector store → retrieve (with provenance). Domain and
application layers stay origin-agnostic; they do not model tickets, Jira, or
other provider types as permanent core entities.

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

Requirements analysis and chat-time tool selection share one chat surface.
A General-mode query is matched by the pack intent policy:

- explicit ``analyze|review … requirements|story`` → ``AnalyzeRequirements``
  (filter-less cross-source retrieval, structured findings, citations)
- explicit generate/risk phrasing → evidence bundle → ordered tool chain
  through the opaque ``InvokeTool`` boundary → ``AskResponse`` with opaque
  ``tool_outputs`` and citations from the raw hits
- anything else → grounded RAG via ``AskKnowledge``

There is no separate requirements-analysis form: paste the story into chat
with an analysis cue (for example ``Analyze these requirements: …``).

Software Delivery requirements analysis (`AnalyzeRequirements`) receives
retrieval through a single-argument callable wired in composition — no
`metadata_filters` channel — with `RELEVANCE_THRESHOLD` applied before hits
reach the pack, mirroring the insufficient-evidence semantics documented for
`AskKnowledge`. Chat-time analysis is gated with the pack via
`software_delivery_tools_enabled` / ``DOMAIN_TOOL_PACKS`` (same gate as
tool-augmented ask).

One domain tool consumes a multi-source evidence bundle. A new source kind does
not require a new risk tool or shared-core contract change. Absence-based
policies (for example missing acceptance criteria) apply only when evidence is
marked complete; chunk-level evidence may still contribute positive signals.

The Streamlit **Software Delivery tool-result renderers** (#161) expose typed
composition views — risk score with factor citations, structured test cases,
and Markdown preview/download — from **test fixtures only**; no adapter feeds
them from a live run yet. They are absent when the pack is disabled, gated by
``software_delivery_tools_enabled`` rather than by catching
``ConfigurationError``. There is no standalone tool-run form: the only path that
retrieves and orchestrates is the chat-time one described below.

``AskResponse.tool_outputs`` remains ``Sequence[InvokeToolResponse]`` — opaque
tool name plus opaque result string. Generic ``InvokeTool``, ``AskResponse``,
and shared Streamlit code never interpret pack payloads. Presentation views
(``SoftwareDeliveryRunView``, ``ToolCallView``, etc.) are **not** stored on
``AskResponse``.

The generic ``ToolCallView`` envelope carries tool name, success/failure
status, and an explicitly authored summary (≤120 characters) built from typed
metadata such as score or generated-case count — never from
``InvokeToolResponse.result`` or truncated opaque payloads. Raw tool payloads
are never stored, exposed, or rendered. Shared Streamlit code stays
pack-agnostic; Software Delivery renderers live in ``tool_run_panel.py``.
``AskResponse.tool_outputs`` is never populated by ``AskKnowledge`` itself: the
application layer may not import ``packs``, so the vocabulary that recognises a
tool request cannot live there.

#### Chat-time tool selection (#170)

``ToolAugmentedAsk`` (``composition/tool_augmented_ask.py``) wraps
``AskKnowledge`` and asks the enabled pack's deterministic policy —
``select_chat_intent`` in ``packs/software_delivery/chat_intent.py`` — which
workflow, if any, a query names. **Selection runs only in General mode**
(``AskRequest.prompt_key is None``). Any selected task prompt delegates the
original request, history, and generation settings unchanged to
``AskKnowledge`` — routing never moves into Streamlit. Unmatched General-mode
queries are delegated to the grounded path verbatim, so ordinary chat is
unchanged and no tool runs speculatively.

Matched intents are either requirements analysis (``analyze|review …
requirements|story`` with a non-empty body after the cue →
``RequirementsAnalyzer``), a generate/risk tool chain, or neither. Generation
wins over analysis; analysis wins over risk-only.

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
the risk``, ``Do not analyze these requirements``). Constraint wording after a match (``Create test cases that do not
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
band and rationale — never from a second model call.

Two properties are worth naming because they are easy to lose:

- **Input safety still applies.** A tool turn skips ``AskKnowledge``, but it
  retrieves through ``RewriteAndRetrieveKnowledge``, which applies
  ``reject_unsafe_query`` and the length cap before returning hits — and hits
  are required before any tool is invoked.
- **Citations come from the raw hits**, not from the evidence bundle, which
  merges chunks by ``(source_type, source_id)`` and loses ``chunk_index``.
  Row-level provenance survives only outside that merge.

Streamlit surfaces a tool turn generically: the answer carries the substance,
and ``tool_output_lines`` names each tool and measures its payload without
parsing it. Projecting opaque outputs into ``SoftwareDeliveryRunView`` for the
#161 renderers remains a separate pack-specific adapter — ``app.py`` cannot
import a pack-named renderer without breaking its own source scan.

#### Tool invocation boundary (#92 vs #95 vs #161 vs #170)

- **#92** — pack-local contracts and scoring; generic ``ToolRegistry`` + single-tool
  ``InvokeTool`` that treats arguments and results as opaque strings.
- **#95** — orchestration over a retrieved evidence bundle (delivered).
- **#161** — presentation-only renderers and the generic ``ToolCallView`` envelope;
  testable with fixtures.
- **#170** — chat intent → retrieve/orchestrate → populate
  ``AskResponse.tool_outputs`` with opaque ``InvokeToolResponse`` entries
  (delivered). The pack-specific projection adapter that would feed the #161
  renderers from those outputs is still open.

### Grounded ask: system policy vs optional task prompts

Chat over ingested documents is orchestrated by `AskKnowledge`, and the four
inputs sit in **different privilege tiers**. The tier is decided by placement,
not by wording — a rule stated in prose can be argued with by text the model
reads later, but text that never reaches the system role cannot impersonate the
policy that constrains it.

| Tier | Input | Placement |
|---|---|---|
| Platform policy | `GROUNDED_RAG_SYSTEM` (`application/grounded_rag_policy.py`) | the `system` argument, **alone** |
| Untrusted evidence | retrieved chunks with provenance | a `Message` between `BEGIN/END_RETRIEVED_CONTEXT` markers |
| Optional task instruction | the selected Mode's `PromptVariant.system` | a `Message` after the context |
| User input | `AskRequest.query` | the final user `Message` |

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
it as a selectable Mode. `AskRequest.prompt_key=None` means General mode (no
task template), and Streamlit defaults to it.

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
`DOCUMENT_CATALOG_PATH` configures only the JSON catalog **file location**; it
does not select an adapter. Composition currently wires `JsonDocumentCatalog`
directly. Configurable JSON vs SQL adapter selection will be introduced by
follow-up [#131](https://github.com/mahmoudazaid/Kernector/issues/131); it is
not implemented here.

## Error taxonomy

Operational failures cross the port boundary as typed errors so presentation can
show user-safe messages instead of vendor bodies or tracebacks. Adapters raise
fixed, adapter-authored exception text with vendor detail only on `__cause__`.
Presentation does **not** treat that text as display-safe: `run_ask_turn` maps
operational types to fixed category sentences (see below).

| Category | Type | Layer | Meaning |
|---|---|---|---|
| validation | `ApplicationValidationError`, `UnknownPromptError`, `UnknownDocumentError` | application | Contract / input reject |
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
| pack | `RequirementsAnalysisValidationError` | domain | Invalid requirements-analysis caller input or prompt budget |
| pack | `RequirementsAnalysisOutputError` | domain | Invalid requirements-analysis model output (`ProviderError` subclass) |
| pack | `MissingEvidenceError` | domain | No retrieval hits cleared the relevance threshold for requirements analysis |
| ingest / documents | `IngestFailure`, `DocumentManagementError`, `Partial*Failure` | application | Upload / catalog mutation failures |
| corpus / catalog / extract | `CorpusLoadError`, `CatalogError`, `DocumentExtractionError` (+ subclasses) | infrastructure | Adapter I/O for seed, catalog, file extract |
| composition | `KnowledgeLoadError`, `DocumentUploadError`, `DocumentOperationError`, `PartialDocumentOperationError` | composition | Presentation-facing wraps of infrastructure / adapter failures |

**Empty / below-threshold retrieval is not an error.** `AskKnowledge` returns
`AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER, citations=())` and does not
call the model.

Streamlit ask mapping (`run_ask_turn`) uses a **fixed type → message map**.
Exception type alone is never treated as proof that `str(error)` is safe:

| Caught type | User-facing message | `drop_user_turn` |
|---|---|---|
| `ApplicationValidationError` | boundary-authored `str(error)` | yes |
| `ProviderError` (incl. `QueryRewriterError`, `QueryRewriteFailure`, `RequirementsAnalysisOutputError`) | fixed provider sentence | no |
| `ToolFailureError` | fixed tool sentence | no |
| `VectorStoreError`, `DomainValidationError`, other `RuntimeError` | fixed operational sentence | no |

Technical and vendor detail may remain on `__cause__` (and in logs); it must
not reach `st.error`.

Streamlit requirements-analysis mapping (`run_analysis_turn`) uses the same
fixed type → message policy:

| Caught type | User-facing message |
|---|---|
| `ApplicationValidationError` | boundary-authored `str(error)` |
| `ProviderError` (incl. `RequirementsAnalysisOutputError`) | fixed provider sentence |
| `InsufficientEvidenceError` | fixed insufficient-evidence sentence |
| `DomainValidationError`, `VectorStoreError`, other `RuntimeError` | fixed operational sentence |
| anything else | logged, generic unexpected sentence |

## Architecture tests

Automated AST checks under `test/architecture/` and
`test/domain/test_domain_boundaries.py` fail when a layer imports a forbidden
package or when application code references Streamlit `session_state`.

Run only the architecture boundary tests:

```bash
uv run pytest test/architecture test/domain/test_domain_boundaries.py
```

A full suite run includes those checks:

```bash
uv run pytest
```
