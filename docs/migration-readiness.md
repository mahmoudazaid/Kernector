# Feature-migration readiness checklist

Closed-out guidance for moving product behavior onto the Next.js + FastAPI
presentation stack. Use this when adding or retargeting a feature that must
reach the browser through versioned HTTP contracts. This document does **not**
implement migrations.

Parent epic: [#124](https://github.com/mahmoudazaid/Kernector/issues/124).
Dual-stack CI: [#128](https://github.com/mahmoudazaid/Kernector/issues/128).
Architecture: [ADR 0002](adr/0002-nextjs-presentation-migration.md).
Streamlit retirement: [ADR 0004](adr/0004-retire-streamlit-presentation.md)
([#228](https://github.com/mahmoudazaid/Kernector/issues/228)).

## Checklist

A feature is ready for the Next.js + HTTP path only when all of the following
hold:

1. **Application contract** — The behavior is owned by an application use case
   (not client-only UI state). The same use case is (or will be) exposed via a
   versioned `/api/v1` route with OpenAPI schemas and RFC 9457 Problem Details
   for failures.
2. **Typed client** — OpenAPI artifacts are regenerated (`cd web && npm run
   api:generate`); `npm run api:check` is green; the Next client consumes the
   generated types (no hand-rolled duplicate DTOs).
3. **UI acceptance parity** — Next.js covers the happy path and the key
   error/empty/unavailable states for that feature against the same application
   contracts (citations, sanitized errors, etc. as applicable).
4. **Dual-stack CI green** — PR CI (Python tests including architecture
   boundaries, Next lint/typecheck/test/build, OpenAPI drift) passes.
5. **No live-model requirement for foundation gates** — Contract and foundation
   tests do not require real external model or embedding calls.

### Settings controls (#237)

Satisfied for provider/model/settings catalog + Ollama probe + Next Settings UI
(client-local persistence under `kernector:runtime-settings:v1`). Ask-turn
consumption of those selections is owned by the chat parity ticket (#235).

### Grounded chat (#235)

Satisfied for `POST /api/v1/chat/ask` (composition → `GroundedAsk`), OpenAPI +
typed client, and Next `/chat` (history, citations, tools-used, projected tool
results, run details, rejected/operational/unavailable states). Transcript
persistence uses `kernector:chat-messages:v1`.

**Known gap:** test-case MD/JSON/CSV/PDF export did not reach Next.js parity
and is tracked in [#243](https://github.com/mahmoudazaid/Kernector/issues/243)
(client-side export).

### Document upload/ingest (#236)

Satisfied for `GET/POST/PUT/DELETE /api/v1/documents` (composition document seam),
OpenAPI + typed client, sanitized wire projection (`has_error` /
`error_summary`), and Next `/documents` (list, upload-new, explicit replace,
delete-with-confirm, empty catalog, list-load failure banner, unavailable).
Upload size/suffix validation is enforced in the HTTP route (413/422) with
client pre-flight for UX. Run a single uvicorn worker until the catalog store
is multi-process safe.

## Out of scope for readiness alone

- Public deployment or production hardening
- Migrating unrelated features in the same ticket
