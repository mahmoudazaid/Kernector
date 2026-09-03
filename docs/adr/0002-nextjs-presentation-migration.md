# ADR 0002: Next.js presentation migration and HTTP contracts

## Status

Accepted

## Context

Kernector’s Clean Architecture keeps business logic out of UI frameworks:
`presentation → composition → application → domain`, with Streamlit as the
current interactive adapter under `presentation/streamlit/`. A second web UI
cannot import Python packages; it must speak HTTP to a presentation adapter.

[EPIC #124](https://github.com/mahmoudazaid/Kernector/issues/124) establishes
Next.js as the future web presentation layer while Streamlit remains
operational during an incremental migration. This ADR records the target
dependency direction, ownership boundaries, API contract strategy, error and
versioning conventions, coexistence/rollback/retirement criteria, and
architecture-test follow-ups before FastAPI routes or Next.js pages ship.

[#100](https://github.com/mahmoudazaid/Kernector/issues/100) (Next.js adapter
contract docs) is already closed as superseded by this track
(`#124` / `#125` / `#81` / `#127`).

## Decision

1. **Target flow** — Next.js reaches the Python stack only over HTTP. **Product
   endpoints** use the versioned prefix `/api/v1/…`; operational health remains
   the intentionally unversioned `GET /health`. Next.js may call both. The
   FastAPI adapter is a presentation peer to Streamlit and wires through
   composition:

```text
web/ (Next.js) ──HTTP──> presentation/http/ (FastAPI)
                              │
                              ▼
                         composition
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
      application                         infrastructure
            │                                   │
            └───────────────► domain ◄──────────┘
```

   Streamlit stays on the existing path (no HTTP required):
   `presentation/streamlit` → `composition` → `application` → `domain`.

2. **Ownership boundaries**
   - **`web/`** — Next.js UI, routing, design system, and typed HTTP client.
     No business rules. Next.js must never **directly import, call, configure,
     or expose** infrastructure adapters.
   - **`presentation/http/`** — FastAPI routes, Pydantic/OpenAPI schemas, CORS,
     and error mapping. Calls `composition` only; must not import
     `infrastructure` or `packs`. Owns server frameworks: `fastapi`,
     `uvicorn`, and `starlette`.
   - **`application/contracts.py`** — UI-agnostic dataclasses for use-case I/O
     (product behavior). Not the wire schema.
   - **`infrastructure/`** — Concrete adapters injected by composition. They
     may run **indirectly** at request time through
     `web/ → HTTP → presentation/http/ → composition → application ports →
     injected infrastructure adapters`. Next.js still must not reach them
     directly.

3. **`web/` isolation** — The TypeScript tree communicates **only** over HTTP
   to the Python API (versioned product routes under `/api/v1/…` and
   unversioned `GET /health`). It must never import Python packages, connect
   to Chroma, call embedding or LLM providers, use document extractors, import
   packs, reach into composition, or otherwise access Python internals.

4. **Contract source of truth** — FastAPI-published **OpenAPI** (from Pydantic
   models that live only in `presentation/http/`) is the single source of
   truth for the generated TypeScript client
   ([#127](https://github.com/mahmoudazaid/Kernector/issues/127)). The HTTP
   adapter maps OpenAPI/Pydantic ↔ `application/contracts.py`. Dual-stack
   contract-drift checks are owned by
   [#128](https://github.com/mahmoudazaid/Kernector/issues/128).

5. **API conventions**
   - **Versioning** — Product endpoints under `/api/v1/…`. Next.js calls these
     for product behavior.
   - **Health** — Unversioned `GET /health` (outside `/api/v1`). Next.js may
     call this for readiness/ops checks without using the product version
     prefix.
   - **CORS** — Allow a configured Next.js origin in development only; no
     permissive production defaults (implemented in
     [#81](https://github.com/mahmoudazaid/Kernector/issues/81)).
   - **HTTPX** — An HTTP **client** library. Legitimate for clients and tests.
     It is not a server-framework boundary and must not be treated as one.
     Server frameworks for the adapter are `fastapi`, `uvicorn`, and
     `starlette` under `presentation/http/` only.

6. **Errors — [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) Problem
   Details** — HTTP failures return `application/problem+json`:

```json
{
  "type": "https://kernector.dev/problems/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "detail": "One or more fields are invalid.",
  "instance": "/api/v1/example",
  "code": "validation_error",
  "request_id": "optional-correlation-id",
  "errors": [
    {
      "pointer": "#/field",
      "detail": "Field-level sanitized message"
    }
  ]
}
```

   | Field | Role |
   | --- | --- |
   | `type`, `title`, `status`, `detail` | RFC 9457 standard |
   | `instance` | Optional RFC 9457 |
   | `code`, `request_id`, `errors` | Kernector extensions |

   Request/semantic validation uses HTTP **422** with the `errors` extension
   for field-level details. Other application/domain failures map to
   appropriate HTTP statuses and stable problem `type` URIs. All
   human-readable values (`title`, `detail`, `errors[].detail`) stay
   sanitized: no tracebacks, provider bodies, prompts, document content, or
   internal identifiers. Detailed type→status mapping is implemented and
   tested in [#81](https://github.com/mahmoudazaid/Kernector/issues/81)
   (sanitized `detail`/`title` may align with Streamlit category sentences
   where useful).

7. **Coexistence, rollback, and Streamlit retirement**
   - Streamlit and Next.js may run during migration. Streamlit entry
     `uv run streamlit run main.py` stays supported.
   - **Rollback** — Stop using Next.js routes and/or disable the HTTP adapter
     process. Streamlit does not depend on FastAPI.
   - **Feature-parity tickets** (separate from epic `#124`) must cover each
     Streamlit capability against the same application contracts before
     retirement is considered.
   - **Objective Streamlit retirement** — All parity tickets done, dual-stack
     CI green (`#128`), and an explicit product decision. Retirement is
     **not** part of `#125` or `#124` definition of done.

8. **Architecture-test follow-ups (not in this ADR’s implementation)**
   - **[#81](https://github.com/mahmoudazaid/Kernector/issues/81)** — Extend
     layer-boundary tests: forbid `fastapi` / `uvicorn` / `starlette` outside
     `presentation` (specifically under `presentation/http/`); keep
     presentation banned from infrastructure, packs, and existing I/O
     denylist packages; do not treat `httpx` as a server framework; optional
     mutual isolation between `presentation/http` and `presentation/streamlit`;
     implement and test RFC 9457 mapping.
   - **[#128](https://github.com/mahmoudazaid/Kernector/issues/128)** —
     Dual-stack CI and OpenAPI/contract-drift checks for `web/`.

   Existing architecture AST checks remain valid for today’s Python tree.

## Consequences

- Contributors must not put FastAPI route logic or OpenAPI schemas in
  `application/` or `infrastructure/`.
- After this ADR (`#125`), shell (`#126`) and HTTP foundation (`#81`) may
  proceed **in parallel**. Typed client (`#127`) starts only after both provide
  the Next.js shell and a live OpenAPI contract. Dual-stack CI (`#128`) follows
  `#126`, `#81`, and `#127`.
- Streamlit remains the supported interactive UI until separate parity work
  and an explicit retirement decision.

## Migration sequence

| Issue | Role | Depends on |
| ----- | ---- | ---------- |
| [#125](https://github.com/mahmoudazaid/Kernector/issues/125) | This ADR + `ARCHITECTURE.md` (docs only) | — |
| [#126](https://github.com/mahmoudazaid/Kernector/issues/126) | Next.js application shell under `web/` | `#125` (may run in parallel with `#81`) |
| [#81](https://github.com/mahmoudazaid/Kernector/issues/81) | Minimal FastAPI under `presentation/http/` (versioned `/api/v1/…` product routes + unversioned `/health`) + boundary/error tests | `#125` (may run in parallel with `#126`) |
| [#127](https://github.com/mahmoudazaid/Kernector/issues/127) | Typed Next.js client from OpenAPI | `#126` and `#81` |
| [#128](https://github.com/mahmoudazaid/Kernector/issues/128) | Dual-stack CI, workflow docs, contract-drift checks | `#126`, `#81`, and `#127` |

Parent: [EPIC #124](https://github.com/mahmoudazaid/Kernector/issues/124).
Coordinates with [#104](https://github.com/mahmoudazaid/Kernector/issues/104)
(broader architecture/ADR docs — this ADR covers the FastAPI/presentation
slice). Supersedes the documentation intent of closed [#100](https://github.com/mahmoudazaid/Kernector/issues/100).

## Related docs

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — layers and Next.js / HTTP migration section
- [ADR 0001](0001-domain-agnostic-knowledge-foundation.md) — domain-agnostic knowledge foundation
