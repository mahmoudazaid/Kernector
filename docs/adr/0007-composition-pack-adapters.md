# ADR 0007: Composition adapters for domain tool packs

## Status

Accepted

## Context

Domain tool packs live under `packs/<pack_id>/` (tools, orchestration, registration).
Chat presentation must not import packs at `import composition` time.

Software Delivery currently uses two composition modules:

- `composition/software_delivery_tools.py` — presentation view dataclasses + enabled helper
- `composition/software_delivery_chat.py` — retrieve → orchestrate → project into `ToolRunOutcome`

Generic composition (`container.py`, `tool_augmented_ask.py`, `tool_runs.py`) stays pack-agnostic.

## Decision

1. **Pack implementations** always go in `packs/<pack_id>/`, never under `composition/`.
2. **Chat + typed UI views** for a pack use a composition pair:
   - `composition/<pack>_tools.py` (views / feature gate)
   - `composition/<pack>_chat.py` (chat-time adapter / projection)
3. Skip that pair only when the pack has no chat projection or typed run views.
4. Keep composition **flat** while there is one (or few) packs. When several packs each need the pair and the root feels crowded, group as:
   `composition/packs/<pack_id>/{chat,tools}.py`
5. Wire packs only from `composition/container.py` (lazy import of pack modules for enabled pack IDs).
6. Do not import pack modules at composition module top level.

## Consequences

- Clear split: packs = domain logic; composition = wiring + presentation boundary.
- Adding a pack without breaking import isolation: new `packs/…` plus optional `*_chat` / `*_tools`, then container/registry wiring.
- Deferred folder rename avoids churn until a second chat-enabled pack lands.