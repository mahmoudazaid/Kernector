# ADR 0005: Consolidate runtime contract on `/api/v1/settings`

## Status

Accepted

## Context

`GET /api/v1/capabilities` was introduced as a minimal read-only prove-out for
the composition boundary. It served that purpose and had no hand-written
frontend consumer; remaining consumers were generated OpenAPI/TypeScript
artifacts and tests.

The endpoint also duplicated `providers` and `default_provider` from
`GET /api/v1/settings`, allowing two contracts to drift.

Runtime constraints were fragmented:

- [#248](https://github.com/mahmoudazaid/Kernector/issues/248) added flat
  `max_input_length` on the settings response.
- `GET /api/v1/documents` returned a `constraints` block for upload size and
  suffixes, so a document-listing endpoint owned global upload policy while
  settings owned the chat limit.

`ARCHITECTURE.md` normally requires incompatible `/api/v1` changes to move to
`/api/v2`. This consolidation is an intentional, ADR-recorded exception while
the Next.js presentation surface is still converging on one bootstrap contract
([#249](https://github.com/mahmoudazaid/Kernector/issues/249)).

## Decision

1. **`GET /api/v1/settings` is the single client-facing runtime contract** —
   providers, env defaults, model-settings catalog, `enabled_packs`, and
   nested `constraints`.

2. **Retire `/api/v1/capabilities`** — delete the route, `CapabilitiesResponse`,
   and related OpenAPI/generated consumers. Do not introduce a second
   capabilities-style endpoint for future packs or constraints.

3. **`constraints` is the extension point** for global server-enforced client
   constraints (`max_input_length`, `max_upload_bytes`,
   `supported_upload_suffixes`). Flat `max_input_length` and a `limits` field
   are not part of the wire contract.

4. **`/documents` no longer exposes upload policy** — listing returns catalog
   rows only. Upload size/suffix validation for the UI reads from settings;
   server-side upload enforcement remains on document operations.

5. **`enabled_packs: string[]` replaces per-pack booleans** — only supported
   configured pack IDs are advertised, in configured order. Unknown configured
   pack IDs are filtered from the response (projection rule); this ticket does
   not turn them into startup errors. Tool-registry construction may still
   reject unknown packs.

6. **Composition injection** — composition seeds application runtime-settings
   defaults with filtered pack IDs and constraints.
   `enabled_domain_tool_packs` stays internal to
   `composition.tool_registry` and is not a public composition package export.

## Consequences

- Chat and Documents UIs share one settings query/cache for runtime policy.
- Providers and default provider have one wire-contract source of truth.
- Adding another domain pack or global constraint extends `/settings` without
  another prove-out endpoint or documents-response migration.
- Future incompatible runtime-contract changes still prefer `/api/v2` unless a
  new ADR records another explicit exception.

## Related docs

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — presentation migration and
  versioning rules
- [README.md](../../README.md) — HTTP entrypoints
- [ADR 0002](0002-nextjs-presentation-migration.md) — Next.js / HTTP foundation
- [ADR 0004](0004-retire-streamlit-presentation.md) — Streamlit retirement
- [#249](https://github.com/mahmoudazaid/Kernector/issues/249) — implementing
  ticket
