# ADR 0006: Workspace scope identity

## Status

Accepted — Decisions 2, 3, 6, and 8 superseded for the live runtime by
[ADR 0007](0007-retire-json-document-catalog.md).

## Context

[#131](https://github.com/mahmoudazaid/Kernector/issues/131) cannot start SQL
catalog work until an approved project/workspace/authorization model exists.
That work is owned by
[EPIC #257](https://github.com/mahmoudazaid/Kernector/issues/257)
(Project Workspaces and Authorization). The first child is
[#258](https://github.com/mahmoudazaid/Kernector/issues/258).

This ADR records the **resolved scope identity** and the **minimal
authorization rule** #131 must persist when SQL is selected. Accepting it
unblocks only #131’s scoped SQL catalog design and implementation. It does
**not** make Kernector multi-tenant-safe.

[#182](https://github.com/mahmoudazaid/Kernector/issues/182) is sign-in and
personalisation only. It explicitly excludes full organisation RBAC and is
**not** delivery of the workspace authorization model.

> **Historical context (superseded by ADR 0007):** Composition formerly wired
> `JsonDocumentCatalog` directly. `DOCUMENT_CATALOG_PATH` selected only that
> JSON file path; it did not choose among adapters. This ADR did not introduce
> SQL adapter selection or a catalog backend switch.

## Decision

1. **Scope identity is `workspace_id`** — a case-sensitive identifier that
   `fullmatch`es `[A-Za-z0-9_-]+` and is at most 64 characters.

2. **~~Server-side configuration only~~** — **Superseded by
   [ADR 0007](0007-retire-json-document-catalog.md).** Resolve `workspace_id`
   only from trusted server-side configuration
   (`DOCUMENT_CATALOG_WORKSPACE_ID`). Never accept it from HTTP requests or any
   user-controlled input. Historical text required validation at
   `load_settings()` whenever the value was present (including under JSON) and
   required it only when SQL was selected. Live runtime: strip/store at load;
   require and validate charset/length when building the SQL catalog.

3. **~~No reserved default~~** — **Superseded by
   [ADR 0007](0007-retire-json-document-catalog.md).** There is no reserved
   `"default"` workspace and no implicit fallback. Historical text: JSON did
   not require `DOCUMENT_CATALOG_WORKSPACE_ID`; selecting SQL or running
   JSON→SQL migration did. Live runtime: SQL is the only catalog; workspace is
   required at catalog build.

4. **SQL uniqueness** is `(workspace_id, source_type, source_id)`. Never global
   `(source_type, source_id)`. `workspace_id` is always bound as a query
   parameter and never interpolated into SQL or DDL — table, schema, or index
   names. The `workspace_id` column uses a case-sensitive (binary or
   deterministic) collation, so the uniqueness constraint preserves
   Decision 1’s case-sensitivity.

5. **Port stays unscoped** — `DocumentCatalog` stays unscoped. Composition
   binds each `SqlDocumentCatalog` instance to **exactly one** `workspace_id`
   at construction; `get` / `all` / `upsert` / `delete` see only that
   workspace.

6. **~~JSON adapter is unscoped~~** — **Superseded by
   [ADR 0007](0007-retire-json-document-catalog.md).**
   `JsonDocumentCatalog` is retired; it is no longer a live adapter.

7. **Minimal authorization rule (SQL)** — the current trusted single-user
   deployment is authorized only for its configured workspace. A bound
   `SqlDocumentCatalog` must not read, update, list, or delete another
   workspace’s rows.

8. **~~JSON→SQL importer~~** — **Superseded by
   [ADR 0007](0007-retire-json-document-catalog.md).** The migrator and migrate
   CLI are removed. Operators with remaining JSON rows must migrate on a prior
   release before upgrading.

## Consequences

- Accepting this ADR unblocks only
  [#131](https://github.com/mahmoudazaid/Kernector/issues/131)’s scoped SQL
  catalog.
- Shared or multi-user deployment stays blocked until
  [#257](https://github.com/mahmoudazaid/Kernector/issues/257) delivers
  authorization-before-retrieval, membership, HTTP workspace selection,
  Chroma/vector/lexical scoping, cross-workspace leakage tests, and safe audit
  events.
- `DOCUMENT_CATALOG_WORKSPACE_ID` is not part of the current JSON runtime.
  `load_settings()` must not require it while JSON is the wired catalog, but
  validates it whenever it is present. It becomes required only when SQL is
  selected or JSON→SQL migration runs — work that remains in #131.
  **Superseded for the live runtime by [ADR 0007](0007-retire-json-document-catalog.md):**
  JSON is retired; workspace is required when building the SQL catalog, not for
  every settings load.

## Related docs

- [ADR 0001](0001-domain-agnostic-knowledge-foundation.md) — catalog port
  (historical JSON wiring superseded by ADR 0007)
- [ADR 0007](0007-retire-json-document-catalog.md) — retires JSON catalog and
  updates workspace load rules
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — catalog adapter selection
- [EPIC #257](https://github.com/mahmoudazaid/Kernector/issues/257) — Project
  Workspaces and Authorization
- [#258](https://github.com/mahmoudazaid/Kernector/issues/258) — this ADR’s
  implementing story
- [#131](https://github.com/mahmoudazaid/Kernector/issues/131) — scoped SQL
  catalog, unblocked by this ADR
- [#182](https://github.com/mahmoudazaid/Kernector/issues/182) — sign-in and
  personalisation; not this model
