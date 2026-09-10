# ADR 0007: Retire JsonDocumentCatalog

## Status

Accepted

## Context

[#131](https://github.com/mahmoudazaid/Kernector/issues/131) added
`SqlDocumentCatalog` and kept `JsonDocumentCatalog` as a temporary unscoped
local adapter. [ADR 0001](0001-domain-agnostic-knowledge-foundation.md) and
[ADR 0006](0006-workspace-scope-identity.md) recorded that dual-backend era.

[#261](https://github.com/mahmoudazaid/Kernector/issues/261) retires the JSON
path after SQL is selected. JSON had no transactions, no safe multi-process
writes, and no `workspace_id` scope.

## Decision

1. **SQL only** — Composition wires only `SqlDocumentCatalog`. Delete
   `JsonDocumentCatalog`, the JSON→SQL migrator, and the migrate CLI.
2. **Retired env keys** — Stop reading `DOCUMENT_CATALOG_BACKEND` and
   `DOCUMENT_CATALOG_PATH`. If either is present and non-blank,
   building the catalog fails with `ConfigurationError` and points operators at
   `DOCUMENT_CATALOG_SQL_PATH` / `DOCUMENT_CATALOG_WORKSPACE_ID`. Process
   bootstrap (`load_settings`, HTTP CORS, OpenAPI export) does not inherit this
   failure.
3. **Catalog config at use** — `load_settings()` stores stripped
   `DOCUMENT_CATALOG_WORKSPACE_ID` and `DOCUMENT_CATALOG_SQL_PATH` when present
   (blank is absent) without charset/length or non-empty path validation, so
   process bootstrap stays catalog-agnostic. Building the catalog requires a
   non-blank SQL path and a valid workspace and raises `ConfigurationError`
   when either is missing or invalid. Unset `DOCUMENT_CATALOG_SQL_PATH` to use
   the `data/catalog/catalog.sqlite` default.
4. **Upgrade path** — Operators with rows in `data/catalog/uploads.json` must
   run the migrator on a release that still ships it, then upgrade. This ADR
   does not reintroduce the migrator.

## Consequences

- ADR 0001 Decision 4 and ADR 0006 Decisions 2, 3, 6, and 8 are superseded for
  the live runtime; their historical text remains for context.
- Unrelated entry points no longer inherit a catalog-only settings failure.
- A leftover `DOCUMENT_CATALOG_BACKEND=json` no longer silently opens an empty
  SQLite catalog.

## Related docs

- [#261](https://github.com/mahmoudazaid/Kernector/issues/261)
- [ADR 0001](0001-domain-agnostic-knowledge-foundation.md)
- [ADR 0006](0006-workspace-scope-identity.md)
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
- [README.md](../../README.md)
