# ADR 0006: Workspace scope identity

## Status

Proposed

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

Composition currently wires `JsonDocumentCatalog` directly.
`DOCUMENT_CATALOG_PATH` selects only that JSON file path; it does not choose
among adapters. This ADR does not introduce SQL adapter selection or a catalog
backend switch.

## Decision

1. **Scope identity is `workspace_id`** — an opaque, case-sensitive, non-blank
   identifier.

2. **Server-side configuration only** — Resolve `workspace_id` only from
   trusted server-side configuration (`KERNECTOR_WORKSPACE_ID`). Reject missing
   and whitespace-only values. Never accept it from current HTTP or any
   user-controlled input.

3. **No reserved default** — There is no reserved `"default"` workspace and no
   implicit fallback. JSON remains the default catalog adapter and does **not**
   require `KERNECTOR_WORKSPACE_ID`. Selecting SQL, or running JSON→SQL
   migration, **requires** an explicit `KERNECTOR_WORKSPACE_ID`.

4. **SQL uniqueness** is `(workspace_id, source_type, source_id)`. Never global
   `(source_type, source_id)`.

5. **Port stays unscoped** — `DocumentCatalog` stays unscoped. Composition
   binds each `SqlDocumentCatalog` instance to **exactly one** `workspace_id`
   at construction; `get` / `all` / `upsert` / `delete` see only that
   workspace.

6. **JSON adapter is unscoped** — `JsonDocumentCatalog` remains an unscoped,
   single-user local adapter and is not governed by `workspace_id`.

7. **Minimal authorization rule (SQL only)** — when SQL is selected, the
   current trusted single-user deployment is authorized only for its configured
   workspace. A bound `SqlDocumentCatalog` must not read, update, list, or
   delete another workspace’s rows. Do not imply the default JSON runtime has
   a configured workspace.

8. **JSON→SQL importer** — takes an explicit target `workspace_id` (the same
   trusted configured value). It does not invent a workspace.

## Consequences

- Accepting this ADR unblocks only
  [#131](https://github.com/mahmoudazaid/Kernector/issues/131)’s scoped SQL
  catalog.
- Shared or multi-user deployment stays blocked until
  [#257](https://github.com/mahmoudazaid/Kernector/issues/257) delivers
  authorization-before-retrieval, membership, HTTP workspace selection,
  Chroma/vector/lexical scoping, cross-workspace leakage tests, and safe audit
  events.
- `KERNECTOR_WORKSPACE_ID` is not part of the current JSON runtime. It becomes
  required only when SQL is selected or JSON→SQL migration runs — work that
  remains in #131 after this ADR is Accepted.

## Related docs

- [ADR 0001](0001-domain-agnostic-knowledge-foundation.md) — catalog port and
  current JSON wiring
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — catalog adapter selection
- [EPIC #257](https://github.com/mahmoudazaid/Kernector/issues/257) — Project
  Workspaces and Authorization
- [#258](https://github.com/mahmoudazaid/Kernector/issues/258) — this ADR’s
  implementing story
- [#131](https://github.com/mahmoudazaid/Kernector/issues/131) — scoped SQL
  catalog (unblocked only after this ADR is Accepted)
- [#182](https://github.com/mahmoudazaid/Kernector/issues/182) — sign-in and
  personalisation; not this model
