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
`build_tools` registers real tools under `tools/` when collaborators are
wired. Drive export (`software_delivery.export_test_cases_google_drive`, #197)
registers when composition supplies both the #305 Markdown render adapter and a
Google Drive `ArtifactUploader` (Hub OAuth client settings required; destination
folder is chosen in the Test Design UI). `chat_model` is optional while only
deterministic tools are registered. Retired tool name constants remain in
`orchestration_policy.py` for dormant chain/projection wiring.

## Google Drive export (#197)

Titles-only POC: tool args are `document_title`, `titles[]`, required
`folder_id`, and optional `file_name`. Composition maps titles through
`application.markdown` and uploads via Hub-user OAuth (`drive.file` preflight).
The folder is selected in the Test Design export dialog — never returned in
tool JSON or public errors. Wireframe:
[`docs/wireframes/export-test-cases-google-drive.html`](../../docs/wireframes/export-test-cases-google-drive.html).

## Chat-time routing (#312)

Composition injects `WorkflowSignal` probes (see
`composition/workflow_signals.py`) into pack-neutral `TurnRouter`:

| Workflow | Recognized | Ready | Incomplete (clarify, never RAG) |
| --- | --- | --- | --- |
| Test Design | Command phrases (`design tests`, `test design`, …); topical questions excluded | Exactly one GitHub Issue locator | Command without Issue (#304) |
| Drive export | Clear or partial export/Drive language | Clear “export … Drive” **and** draft with selected titles **and** agent loop on | Partial phrase (#310); missing titles; agent loop off (`tool_unavailable`) |

Handoff/`Start Test Design` actions are built **after** a ready `tool_workflow`
decision — not as a presentation pre-ask gate.

`select_chat_intent` remains for legacy registration typing; live chat routing
uses WorkflowSignals. Only General chat (`AskRequest.prompt_key is None`) is
eligible for the router; selected task prompts always stay on grounded RAG.

## Test Design workflow (#293)

Pack-local interactive workflow under `test_design/` — **not** a registered
agent `Tool`. Create starts from a **live GitHub Issue** (`source_locator`),
not catalog RAG. Evidence is a single `SourceDocument` from the connector
reader; the pack suggests test candidates and typed coverage gaps, persists a
workspace-scoped draft, and confirms coverage selection (`status: ready`).
Detailed manual/Cucumber scenario generation is deferred to #300.

| Module | Responsibility |
| --- | --- |
| `test_design/models.py` | `TestCoverageDraft`, `TestCandidate`, allowlists |
| `test_design/suggest_tests.py` | Evidence → suggested candidates + gaps → coverage_review draft |
| `test_design/codec.py` / `repository.py` | Opaque payload codec + repository Protocol |

HTTP routes under `/api/v1/test-design/*` are always mounted; when the pack is
disabled they return `test_design_unavailable` without importing this pack.
Composition namespace for persistence: `software-delivery:test-design`.
Chat routing clarifies incomplete Test Design commands (#304) and builds the
Start handoff only after a ready `tool_workflow` decision (intent + one Issue).

Enable with `DOMAIN_TOOL_PACKS=software-delivery`.
