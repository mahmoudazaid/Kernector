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
folder is chosen in the Test Design UI). The export carries the selected titles
plus each available case: Cucumber as one fenced feature file (shared Feature and
Background) and Manual as numbered Preconditions, Steps, and Expected result.
Tests that need more detail from the ticket are listed by title only. `chat_model` is optional while only
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
`composition/chat/workflow_signals.py`) into pack-neutral `TurnRouter`:

| Workflow | Recognized | Ready | Incomplete (clarify, never RAG) |
| --- | --- | --- | --- |
| Test Design | Command phrases (`design tests`, `test design`, …); docs/topical mentions without an Issue locator excluded | Exactly one GitHub Issue locator | Leading command without Issue (#304) |
| Drive export | Clear or partial export/Drive language (docs/prose mentions excluded) | Clear “export … Drive” **and** draft with selected titles **and** agent loop on | Partial phrase (#310); missing titles; agent loop off (`tool_unavailable`) |

Handoff/`Start Test Design` actions are built **after** a ready `tool_workflow`
decision — not as a presentation pre-ask gate.

`select_chat_intent` remains for legacy registration typing; live chat routing
uses WorkflowSignals. Only General chat (`AskRequest.prompt_key is None`) is
eligible for the router; selected task prompts always stay on grounded RAG.

## Test Design workflow (#293 / #300)

Pack-local interactive workflow under `test_design/` — **not** a registered
agent `Tool`. Create starts from a **live GitHub Issue** (`source_locator`),
not catalog RAG. Evidence is a single `SourceDocument` from the connector
reader; the pack suggests test candidates, persists a workspace-scoped draft,
and confirms coverage selection (`status: ready`) with per-candidate
`manual` / `cucumber` chosen on the same Coverage step. Next then generates
grounded detailed cases (`status: case_editing`) for edit/save via CAS.
Cucumber drafts share one
`cucumber_feature` + `cucumber_background`; each case stores Scenario-only
`gherkin`. Manual cases store independent Preconditions, Steps (action
strings), and Expected Result — Kernector is the source of truth; destination
sync (Xray, AssertThat, Drive, etc.) is an outbound adapter responsibility.
The Cases UI packages Cucumber (one Feature), Manual (three numbered lists),
and Needs clarification (`insufficient_evidence`). Confirm on `case_editing`
is a no-op that keeps artifacts. Changing coverage fields demotes to
`coverage_review` and clears generated cases; type-only or artifact edits do
not. Generate re-fetches the Issue and compares `evidence_fingerprint`;
mismatches fail closed without writing. Regeneration is explicit and never
silently overwrites `user_edited` cases unless `overwrite_edited=true`.

| Module | Responsibility |
| --- | --- |
| `test_design/models.py` | `TestCoverageDraft`, `TestCandidate`, `GeneratedTestCase`, allowlists |
| `test_design/suggest_tests.py` | Evidence → suggested candidates → coverage_review draft |
| `test_design/generate_cases.py` | Confirmed draft + evidence → detailed cases |
| `test_design/codec.py` / `repository.py` | Opaque payload codec (schema v4) + repository Protocol |

HTTP routes under `/api/v1/test-design/*` are always mounted; when the pack is
disabled they return `test_design_unavailable` without importing this pack.
Endpoints: create/get/patch/confirm, `POST .../generate`, Drive export.
Composition namespace for persistence: `software-delivery:test-design`.
Chat routing clarifies incomplete Test Design commands (#304) and builds the
Start handoff only after a ready `tool_workflow` decision (intent + one Issue).

Enable with `DOMAIN_TOOL_PACKS=software-delivery`.

## Test Design over MCP (#338)

[`tools/test_design_mcp.py`](tools/test_design_mcp.py) exposes the same
workflow to allowlisted MCP clients. The pack owns the tool ids and dispatch;
composition ([`composition/mcp/test_design.py`](../../composition/mcp/test_design.py))
owns the argument/result schemas and projection. `build_mcp_tools()`
contributes these tools only when composition supplies a workspace-bound
`test_design_binding`. The pack never sees the workspace id.

| Tool id | Arguments | Existing operation |
| --- | --- | --- |
| `software_delivery.test_design_start` | `issue_locator` (GitHub Issue URL or `owner/repo#number`, or Jira Data Center key `PROJ-123` or browse URL) | create draft from the one source that accepts the locator |
| `software_delivery.test_design_get` | `draft_id` | read draft |
| `software_delivery.test_design_confirm` | `draft_id`, `expected_version`, `candidate_ids` (1 to 40) | patch selection, then confirm |
| `software_delivery.test_design_generate` | `draft_id`, `expected_version`, optional `candidate_ids` (at most 20), `type_overrides[{candidate_id, test_type}]`, `overwrite_edited` | #300 generate |

- Arguments are strict (`additionalProperties: false`); `workspace_id` and
  `conversation_id` are never accepted. Each MCP draft gets a server-generated
  `mcp-<uuid>` conversation id, so it cannot collide with a chat conversation.
- Results omit `workspace_id`, `conversation_id`, `evidence_fingerprint`, the
  draft-level `source_reference`, and any OAuth or provider data. Candidate
  `evidence_references` still carry the Issue `source_id`
  (`issue:<GitHub node id>`).
- `untrusted_model_output` marks model-generated text only: suggested
  candidates, generated cases, and the shared Cucumber feature and background.
  User-added (`origin: manual`) candidates are `false`. Server metadata
  (`draft_id`, `status`, `version`, ids) carries no marker.
- Confirm makes two compare-and-swap writes, so the version advances by 2 from
  `coverage_review` (by 1 when already `ready` with the same selection). If
  confirm fails after the selection is saved (for example
  `evidence_changed`), re-read with `software_delivery.test_design_get`.
- Errors: `validation_error`, `not_found` (unknown and other-workspace drafts
  are identical), `version_conflict`, `evidence_changed`,
  `source_not_connected`, `insufficient_evidence`, otherwise `internal_error`.
  Nothing is published externally.
- `source_not_connected` payloads also carry
  `"legacy_code": "github_not_connected"` for one release so existing clients
  keep working. Match on `code`; `legacy_code` will be removed.
- Live sources are resolved through the composition-owned Test Design source
  registry (#351). GitHub Issues is the only registered source; drafts persist
  their `source_provider` so confirm and generate re-fetch from the same one.
