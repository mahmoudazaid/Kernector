# ADR 0008: Group modules by concern in every layer

## Status

Accepted

## Context

Layer roots have grown flat. `application/` holds 38 modules side by side
(`ask_*`, `evaluate_*`, `rag_judge_*`, `tool_approval`, …), `domain/` holds 10,
and `packs/software_delivery/` holds 10 next to its `test_design/` and `tools/`
packages. Finding the code for one concern means scanning a long alphabetical
list, and nothing stops the next module from landing there too.

The composition root drifted the same way. While adding Jira Data Center as a
Test Design source (#353), `composition/container.py` gained a Jira-specific
builder (default state store, default HTTP client) that duplicated defaults
already owned by `composition/jira/data_center.py`. The container is meant to
decide *whether* a concern is wired, not *how* it is built.

[ADR 0007 (pack adapters)](0007-composition-pack-adapters.md) Decision 4 said
to keep `composition/` flat until several packs exist. In practice
`composition/` already groups by concern (`chat/`, `github/`, `jira/`, `mcp/`,
`software_delivery/`, `test_design/`, `tools/`), and the flat pair
`<pack>_tools.py` / `<pack>_chat.py` it describes now lives in
`composition/software_delivery/`.

## Decision

1. **New modules go into a concern package, never a layer root.** Layer roots
   are `domain/`, `application/`, `infrastructure/`, `presentation/`,
   `composition/`, and each `packs/<pack_id>/`. A concern is a feature or
   capability (`ask`, `evaluation`, `tool_approval`, `test_design`, `jira`,
   `connectors`), not a technical kind (`utils`, `helpers`, `models`, `misc`).
2. **Shape per layer:**
   - `domain/<concern>/` and `application/<concern>/` for entities, ports, use
     cases, and policies of one concern.
   - `infrastructure/<capability>/<provider>/` (for example
     `infrastructure/connectors/jira/`).
   - `presentation/<transport>/…` with one route module per concern
     (`presentation/http/routes/<concern>.py`).
   - `composition/<concern>/`, with one module per provider inside it when a
     concern has pluggable providers (`composition/test_design/github_source.py`,
     `composition/test_design/jira_data_center_source.py`).
   - `packs/<pack_id>/<feature>/`.
3. **Split before it gets flat.** When a package would hold more than about
   eight modules, or three or more modules share a prefix (`rag_judge_*`),
   group them into a sub-package. When one provider needs more than one module
   inside a concern, give it a sub-package there.
4. **The composition root stays a switchboard.** `composition/container.py`
   reads settings, decides which concerns and providers are active, and calls
   one lazily imported builder per concern. Provider defaults (state stores,
   HTTP clients, adapters) live in that concern's package, next to the code
   that uses them. The container does not import provider packages under
   `infrastructure/connectors/` directly.
5. **Existing root modules are grandfathered, not frozen forever.** The
   current root modules may stay until the concern is next touched; moving
   them is welcome and needs no separate ADR. The list only shrinks.
6. **Enforced by tests.** `test/architecture/test_layer_grouping.py` fails
   when a new module appears at a layer root, when a grandfathered module
   is moved but still listed, or when the container imports a provider
   connector package outside the grandfathered set.
7. **Supersedes** [ADR 0007 (pack adapters)](0007-composition-pack-adapters.md)
   Decisions 2 and 4: pack adapters live in `composition/<pack>/`
   (`chat.py`, `tools.py`, …), not as flat `composition/<pack>_*.py` files.

## Consequences

- Each concern has one obvious home in every layer, and adding a provider
  touches that concern's package plus one registration line in the container.
- The grandfather lists in the architecture test record the remaining
  cleanup (for example `application/`), and moving a module requires deleting
  its entry.
- Moving modules changes import paths. Do it in focused refactors, not mixed
  into feature work.
- `composition/container.py` no longer grows with each provider.

## Related docs

- [ADR 0007 (pack adapters)](0007-composition-pack-adapters.md)
- [#353](https://github.com/mahmoudazaid/Kernector/issues/353)
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
