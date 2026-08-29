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
default product surface uses the neutral `core` prompt pack and
`data/knowledge/documents.json`.

### Replaceable connectors

Connectors normalize external payloads into `SourceDocument` before the shared
pipeline. Names only (no implementation commitment in this document):

- File upload (TXT, Markdown, PDF)
- Seed JSON corpus adapter
- Future: GitHub, Jira, Confluence, Google Drive

### Catalog adapter selection

Uploaded-document lifecycle metadata uses `DocumentCatalog`. Today composition
wires `JsonDocumentCatalog` via `DOCUMENT_CATALOG_PATH`. A transactional SQL
adapter is tracked as configuration/selection follow-up
[#131](https://github.com/mahmoudazaid/Kernector/issues/131); it is not
implemented here.

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
