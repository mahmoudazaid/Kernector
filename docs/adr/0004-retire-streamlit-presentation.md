# ADR 0004: Retire Streamlit presentation

## Status

Accepted

## Context

[ADR 0002](0002-nextjs-presentation-migration.md) §7 set objective criteria for
Streamlit retirement: feature-parity tickets done, dual-stack CI green, and an
explicit product decision. Those criteria are met:

- Parity tickets [#235](https://github.com/mahmoudazaid/Kernector/issues/235)
  (chat), [#236](https://github.com/mahmoudazaid/Kernector/issues/236)
  (documents), and [#237](https://github.com/mahmoudazaid/Kernector/issues/237)
  (settings) landed on Next.js against the FastAPI `/api/v1` contracts.
- Dual-stack CI ([#128](https://github.com/mahmoudazaid/Kernector/issues/128))
  already ran Python + Next foundation jobs with **no** Streamlit job.
- This ADR is the explicit product decision to retire Streamlit.

### Parity evidence

| Streamlit capability | Next.js / HTTP owner |
| --- | --- |
| Grounded chat | [#235](https://github.com/mahmoudazaid/Kernector/issues/235) — `/chat`, `POST /api/v1/chat/ask` |
| Document upload / ingest | [#236](https://github.com/mahmoudazaid/Kernector/issues/236) — `/documents`, `/api/v1/documents` |
| Provider / model settings | [#237](https://github.com/mahmoudazaid/Kernector/issues/237) — `/settings`, `GET /api/v1/settings` |
| Test-case MD / JSON / CSV / PDF export | **NONE** — owned by follow-up [#243](https://github.com/mahmoudazaid/Kernector/issues/243) |

## Decision

1. **Sole interactive UI** — Next.js (`web/`) plus the FastAPI adapter under
   `presentation/http/` is the only interactive presentation stack. The CLI
   remains a non-interactive presentation entrypoint.

2. **Delete Streamlit surface** — Remove `presentation/streamlit/`, process
   entry `main.py`, `.streamlit/` config, and the `streamlit` dependency.

3. **Delete the export stack** — Remove `composition/conversation_export`,
   `infrastructure/export/`, and the `fpdf2` dependency. That stack was
   misnamed: it never exported conversations; it only ever faked test-case PDF
   download via Streamlit `cases_export`. Client-side test-case export under
   [#243](https://github.com/mahmoudazaid/Kernector/issues/243) is the correct
   home. **`pypdf` stays** for PDF ingest.

## Consequences

- **Knowingly dropped capability** — test-case MD/JSON/CSV/PDF export has no
  Next.js owner yet; track recovery in
  [#243](https://github.com/mahmoudazaid/Kernector/issues/243).
- **Not a loss** — “conversation export” never existed as a real product
  feature and is not wanted; deleting the misnamed export modules does not
  remove a shipped conversation-transcript path.
- Re-adopting Streamlit (or another interactive Python UI framework) requires a
  **new ADR**; this decision is not rolled back by restoring deleted files
  without one.

## Related docs

- [ADR 0002](0002-nextjs-presentation-migration.md) — coexistence / retirement
  criteria (superseded in part by this ADR)
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — layers and presentation boundaries
- [docs/migration-readiness.md](../migration-readiness.md) — closed-out feature
  migration guidance
- [#228](https://github.com/mahmoudazaid/Kernector/issues/228) — retire
  Streamlit implementation ticket
- [#243](https://github.com/mahmoudazaid/Kernector/issues/243) — test-case
  export follow-up
