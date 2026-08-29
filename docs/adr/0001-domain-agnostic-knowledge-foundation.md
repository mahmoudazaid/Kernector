# ADR 0001: Domain-agnostic knowledge foundation

## Status

Accepted

## Context

Early Kernector models treated work-item / SDLC concepts (notably a shared
`Ticket` type and a closed `SourceType` set) as part of the reusable core. Seed
corpora and prompts also read as if Story Intelligence vocabulary were
platform-wide requirements.

[EPIC #68](https://github.com/mahmoudazaid/Kernector/issues/68) targets a
**generic knowledge foundation**: arbitrary sources and documents, with optional
**domain packs** for product meaning and **connectors** that normalize provider
data into a shared document contract.

## Decision

1. **Core** — Domain and application operate on generic documents
   (`SourceDocument`, provenance, chunks, catalog, vector-store ports). The
   shared pipeline is: normalize → chunk → embed → store → retrieve. Core does
   not retain `Ticket` or a closed `SourceType` enum as permanent types.
2. **Domain packs** — Optional. Story Intelligence is the first example
   (knowledge samples under `data/knowledge/packs/`, prompts under
   `prompts/packs/`). Pack-specific fields are metadata for that pack, not
   universal schema requirements.
3. **Connectors** — Replaceable adapters (upload files, seed JSON corpus,
   future GitHub / Jira / Confluence / Drive, and others) map provider payloads
   into `SourceDocument` before calling the shared pipeline. Connector
   implementation is out of scope for this ADR.
4. **Catalog persistence** — Uploaded-document catalog uses a port
   (`DocumentCatalog`). Composition currently wires `JsonDocumentCatalog`
   directly. `DOCUMENT_CATALOG_PATH` sets only that JSON adapter’s file path; it
   does not choose among adapters. Configurable JSON vs SQL adapter selection
   is tracked in [#131](https://github.com/mahmoudazaid/Kernector/issues/131).

## Consequences

- Seed JSON under `data/knowledge/` is an **on-disk adapter input**, not a
  universal contract for every connector.
- SDLC-shaped fields (`severity`, `component`, illustrative `doc_type` values)
  remain optional opaque metadata in example packs.
- Documentation and tests should describe core vs pack vs connector boundaries
  so contributors do not reintroduce ticket-centric APIs into domain or
  application contracts.

## Migration sequence

| Issue | Role |
| ----- | ---- |
| [#132](https://github.com/mahmoudazaid/Kernector/issues/132) | Remove `Ticket` and `SourceType.TICKET` from domain |
| [#133](https://github.com/mahmoudazaid/Kernector/issues/133) | Opaque string-backed `source_type` |
| [#134](https://github.com/mahmoudazaid/Kernector/issues/134) | Documents-only ingest contract |
| [#135](https://github.com/mahmoudazaid/Kernector/issues/135) | Generic ask grounding (no `AskRequest.ticket`) |
| [#136](https://github.com/mahmoudazaid/Kernector/issues/136) | Interview-prep prompts → Story Intelligence pack |
| [#137](https://github.com/mahmoudazaid/Kernector/issues/137) | Seed corpus as example pack + neutral samples |
| [#138](https://github.com/mahmoudazaid/Kernector/issues/138) | Document foundation, packs, and connector boundaries |
| [#131](https://github.com/mahmoudazaid/Kernector/issues/131) | Configurable JSON/SQL catalog adapter selection |

Parent: [EPIC #68](https://github.com/mahmoudazaid/Kernector/issues/68).

## Related docs

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — layers and knowledge-foundation section
- [data/knowledge/README.md](../../data/knowledge/README.md) — seed format and domain mapping
