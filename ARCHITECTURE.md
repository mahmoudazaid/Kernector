# Architecture

Kernector is organised into layered packages so that UI frameworks cannot own
business logic and the UI stays replaceable.

## Layers

| Layer | Responsibility | May import |
|---|---|---|
| `domain/` | Entities, validation, and port protocols | Standard library only |
| `application/` | Use cases and typed request/response contracts | `domain` |
| `infrastructure/` | Concrete adapters and external integrations | `domain` and approved third-party libraries |
| `composition/` | Settings loading, factories, and dependency injection | `application`, `domain`, and `infrastructure` |
| `presentation/` | Streamlit and future UI adapters | `application`, `domain`, and `composition` |

## Allowed dependency directions

```text
presentation ──> composition ──> application ──> domain
                      │                              ▲
                      └────────> infrastructure ─────┘
```

Everything points inward toward `domain`. Nothing points outward.

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
  joined.
- `presentation` is the only layer allowed to import Streamlit. It must call
  application behavior through `composition` and must not construct or import
  infrastructure adapters directly.

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

Packs supply example content and prompts for a product surface. **Story
Intelligence** is the first example (`data/knowledge/packs/story-intelligence/`,
`prompts/packs/story-intelligence/`). Pack fields (for example SDLC-shaped
`doc_type` or `severity`) are example metadata, not platform requirements. The
default product surface may enable the neutral `core` prompt pack and
`data/knowledge/documents.json`, but **task-prompt packs are optional**: the
app starts and General mode works with zero enabled packs.

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
