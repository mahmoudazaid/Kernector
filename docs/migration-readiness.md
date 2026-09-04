# Feature-migration readiness checklist

Objective criteria for migrating an individual Streamlit feature to the Next.js
presentation stack. Use this before opening a feature-parity ticket or retiring
the Streamlit path for that capability. This document does **not** implement
migrations.

Parent epic: [#124](https://github.com/mahmoudazaid/Kernector/issues/124).
Dual-stack CI: [#128](https://github.com/mahmoudazaid/Kernector/issues/128).
Architecture: [ADR 0002](adr/0002-nextjs-presentation-migration.md).

## Checklist

A feature is ready to migrate only when all of the following hold:

1. **Application contract** — The behavior is owned by an application use case
   (not Streamlit session state). The same use case is (or will be) exposed via
   a versioned `/api/v1` route with OpenAPI schemas and RFC 9457 Problem Details
   for failures.
2. **Typed client** — OpenAPI artifacts are regenerated (`cd web && npm run
   api:generate`); `npm run api:check` is green; the Next client consumes the
   generated types (no hand-rolled duplicate DTOs).
3. **UI acceptance parity** — Next.js covers the Streamlit happy path and the
   key error/empty/unavailable states for that feature against the same
   application contracts (citations, sanitized errors, etc. as applicable).
4. **Dual-stack CI green** — PR CI (Python tests including architecture
   boundaries, Next lint/typecheck/test/build, OpenAPI drift) passes.
5. **Streamlit still works** — `uv run streamlit run main.py` remains supported
   until an explicit product retirement decision; rollback is “stop using the
   Next route / HTTP process.”
6. **No live-model requirement for foundation gates** — Contract and foundation
   tests do not require real external model or embedding calls.

### Settings controls (#237)

Satisfied for provider/model/settings catalog + Ollama probe + Next Settings UI
(client-local persistence under `kernector:runtime-settings:v1`; New chat clears
`kernector:chat-messages:v1` for #235). Ask-turn consumption of those selections
is owned by the chat parity ticket.

## Out of scope for readiness alone

- Public deployment or production hardening
- Removing Streamlit globally
- Migrating unrelated features in the same ticket
