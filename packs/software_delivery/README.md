# Software Delivery pack

Optional executable pack for Software Delivery workflows. Composition reaches
this pack only through [`registration.py`](registration.py).

## Layout

| Location | Responsibility |
| --- | --- |
| `tools/` | Real tool adapters (`tools/<name>.py`), registered from `build_tools` |
| Pack root | Shared contracts, errors, limits, evidence-bundle helpers, orchestration, chat intent, registration |

The three scaffolding tools (`software_delivery.risk_score`,
`software_delivery.generate_test_cases`,
`software_delivery.export_test_cases_markdown`) are **retired** (#285).
`build_tools(*, chat_model=…)` returns an empty sequence. The `chat_model`
keyword stays so the next real tool can take a chat collaborator without a
registry contract change. Retired tool name constants remain in
`orchestration_policy.py` for dormant chain/projection wiring; they are not
invokable while the registry is empty.

## Chat-time intent selection

`select_chat_intent(query)` always returns `None` (**choice A**, #285). Former
risk/generate phrasing stays on grounded RAG. `ChatToolSelection` remains for
registration typing and `ToolAugmentedAsk`'s intent protocol until a real tool
lands.

Composition reaches the selector through `registration.build_chat_intent_selector`.
Only General chat (`AskRequest.prompt_key is None`) is eligible; selected task
prompts always stay on grounded RAG.

## Test Design workflow (#293)

Pack-local interactive workflow under `test_design/` — **not** a registered
agent `Tool`. Create starts from a **live GitHub Issue** (`source_locator`),
not catalog RAG. Evidence is a single `SourceDocument` from the connector
reader; the pack plans coverage candidates, persists a workspace-scoped draft,
generates scenarios for selected candidates only, and confirms a portable draft.

| Module | Responsibility |
| --- | --- |
| `test_design/models.py` | `TestCoverageDraft`, `TestCandidate`, `TestScenario`, gaps, allowlists |
| `test_design/plan_coverage.py` | Evidence → coverage_review draft via `ChatModel` |
| `test_design/generate_scenarios.py` | Selected-only missing scenario generation |
| `test_design/codec.py` / `repository.py` | Opaque payload codec + repository Protocol |

HTTP routes under `/api/v1/test-design/*` are always mounted; when the pack is
disabled they return `test_design_unavailable` without importing this pack.
Composition namespace for persistence: `software-delivery:test-design`.
Chat handoff bypasses grounded RAG when intent + one Issue ref are present.

Enable with `DOMAIN_TOOL_PACKS=software-delivery`.
