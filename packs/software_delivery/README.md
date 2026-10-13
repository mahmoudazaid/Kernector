# Software Delivery pack

Optional executable pack for Software Delivery workflows. Composition reaches
this pack only through [`registration.py`](registration.py).

## Layout

| Location | Responsibility |
| --- | --- |
| `tools/` | Real tool adapters (`tools/<name>.py`), registered from `build_tools` |
| `test_files/` | Pure Robot Framework / Gherkin parser for the test file preview (#396) |
| Pack root | Shared contracts, errors, export limits, chat intent, registration |

The scaffolding risk, test-generation, and Markdown-export tools were retired
(#285), and their deterministic orchestration chain was removed (#365).
`build_tools` registers real tools under `tools/` when collaborators are
wired. Drive export (`software_delivery.export_test_cases_google_drive`, #197)
registers when composition supplies both the #305 Markdown render adapter and a
Google Drive `ArtifactUploader` (Hub OAuth client settings required; destination
folder is chosen in the Test Design UI). The export carries the selected titles
plus each available case: Cucumber as one fenced feature file (shared Feature and
Background) and Manual as numbered Preconditions, Steps, and Expected result.
Tests that need more detail from the ticket are listed by title only. `chat_model` is optional while only
deterministic tools are registered.

## Google Drive export (#197)

Titles-only POC: tool args are `document_title`, `titles[]`, required
`folder_id`, and optional `file_name`. Composition maps titles through
`application.markdown` and uploads via Hub-user OAuth (`drive.file` preflight).
The folder is selected in the Test Design export dialog — never returned in
tool JSON or public errors. Wireframe:
[`docs/wireframes/export-test-cases-google-drive.html`](../../docs/wireframes/export-test-cases-google-drive.html).

## Xray test creation (#199)

| Tool | Arguments | Result |
| --- | --- | --- |
| `software_delivery.create_xray_tests` | `draft_id` (required), `link_source_issue` (default `true`) | `created_keys[]`, `created_count`, `failed_count` |

The tool loads the Test Design draft and turns each available case of a
selected candidate into one Xray test. Manual cases become Manual tests with
one step per action; the expected result goes on the last step. Cucumber cases
become Cucumber tests with Gherkin steps (shared Background first, scenario
headers removed). When `link_source_issue` is true and the draft came from a
Jira issue, each test is linked to that issue with `XRAY_LINK_TYPE`.

The pack only uses `XrayTestImporter` and neutral models from
`domain/test_management/xray.py`. It never sees Jira custom field ids.
`XRAY_DEPLOYMENT` selects the importer:

| Deployment | API used | Schema discovery |
| --- | --- | --- |
| `cloud` | `POST /api/v2/authenticate` (client id and secret), then the GraphQL `createTest` mutation at `/api/v2/graphql` | `getProjectSettings(projectIdOrKey)` test types by `kind` (`Steps`, `Gherkin`) |
| `server` | Jira `POST /rest/api/2/issue` with a Personal Access Token (reuses `JIRA_DC_BASE_URL` / `JIRA_DC_TOKEN`) | Paged `GET /rest/api/2/issue/createmeta/{project}/issuetypes[/{id}]`, finding the Xray fields by custom type key: `com.xpandit.plugins.xray:test-type-custom-field`, `…:manual-test-steps-custom-field`, `…:automated-test-type-custom-field`, `…:steps-editor-custom-field` |

The discovered schema is cached per deployment, base URL, and project. On
`server`, any other required field without a Jira default (components, fix
versions, labels, project-specific custom fields) is filled with no
configuration. Kernector first copies the value from the draft's source Jira
issue, keeping it only if it matches the field's allowed values. If the field
has exactly one allowed value, it uses that. If a field still has no value,
nothing is created and the tool error names the field. Kernector never guesses
a value.

**Duplicates and retries.** Tests are created one at a time with no dedupe
key, so running the tool twice creates a second set. A test Xray rejects
(HTTP 400, GraphQL errors, missing test type) is counted in `failed_count` and
the batch continues. Any other failure stops the batch: if nothing was created
yet the call fails; otherwise the remaining tests are counted as failed and the
created keys are returned. The only retry is one schema rediscovery when the
first create is rejected with a cached schema and nothing has been created.
Approval confirms one call. It is not idempotency.

**Chat.** The tool needs human approval (`ToolApprovalPolicy`). A clear request
such as "create xray tests" with a draft that has generated cases runs the
agent with fixed `{draft_id}` arguments. The approval card shows the project key
and test count, and the receipt lists the created keys.

**MCP.** The same tool class is contributed through `build_mcp_tools` when
Xray is configured and it is allowlisted in `MCP_TOOL_ALLOWLIST`. Every call
goes through the generic MCP approval gate
([ADR 0010](../../docs/adr/0010-mcp-side-effect-tools-shared-registry-hitl.md)).
Clients without elicitation get `approval_required`, and nothing is created.

**Test Design page.** On the Test steps step, **Create in Xray** sits next to
Export to Google Drive when Xray is configured. Its confirm dialog is the
approval: it shows the project, the test count, and the Jira story the tests
link to. `GET /api/v1/test-design/drafts/{draft_id}/export/xray` reports
availability and the keys already created from the draft;
`POST` the same path with `{expected_version}` runs the same tool. Created keys
are stored per draft on every path (page, chat, and MCP), so the dialog warns
"Already created …" before a repeat run. Xray rejections (such as required fields Kernector could not fill) return
502 `xray_export_failed` with a safe detail.

## Test file scenario preview (#396)

| Tool | Arguments | Result |
| --- | --- | --- |
| `software_delivery.preview_test_file_scenarios` | `files[]` of `{path, content}` (1 to 20; `path` ends in `.robot` or `.feature`) | `files[]` of parsed scenario specs, `scenario_count` |

A read-only, pure parser ([`test_files/`](test_files/)). The caller sends each
file's workspace-relative path and full text. Kernector never reads the disk,
never scans a workspace, and makes no Jira or Xray calls; creating tests from
the result is #397 (below). The tool is registered whenever the pack is enabled, on
chat (`InvokeTool`) and on MCP (allowlist it in `MCP_TOOL_ALLOWLIST`), and
needs no approval. Its description tells client agents when to pick it (for
example "what will go to Xray from this feature?") and to read the open or
mentioned file themselves, so users need not name the tool or the path. MCP
clients also get the `preview_xray_scenarios` prompt (in VS Code,
`/mcp.kernector.preview_xray_scenarios`), with an optional `file` argument that
defaults to the file open in the editor. The ticket's "faked Jira/Xray client" criterion does not
apply: the tool takes no client, and the MCP tests run with no Xray
configuration to prove it.

**Limits.** At most 20 files, 512-character paths, 256 KiB per file and
1 MiB in total (UTF-8 bytes), all checked before anything is parsed, and 500
scenarios per call. Errors are `validation_error` with a fixed message
`path:line: reason`; the path is stripped of control characters and long
paths keep only their last 117 characters after `...`. No file content is
echoed.

**Robot Framework.** Only `*** Test Cases ***` entries whose name starts with
`Scenario:` become scenarios; other test cases are skipped. Space (two or
more), tab and pipe separators are supported. Body rows starting with
`Given`, `When`, `Then`, `And` or `But` are steps, with the remaining cells
kept verbatim as arguments; `...` continues the previous step or `[Tags]`.
Tags come from `[Tags]` (multiple rows allowed), `Default Tags` and
`Test Tags` / `Force Tags`. As in Robot, a test with its own `[Tags]` does
not inherit the `Default Tags` plain tags, but a story key there still
applies. An empty scenario name or a `...` with nothing to
continue is rejected.

**Gherkin.** One `Feature:` per file, an optional `Background:` before the
first scenario, `Scenario:` / `Example:`, and `Scenario Outline:` /
`Scenario Template:` with one or more `Examples:` / `Scenarios:` blocks (each
with its own tags, a header row and at least one data row). Steps carry an
optional data table or doc string (`"""` or ```` ``` ````, with media type);
doc-string lines are kept verbatim, including lines that look like comments,
tags, tables or keywords. Outline placeholders stay as written: one outline is
one scenario spec, and Examples rows are not expanded. Rejected with file and
line: `Rule:`, a non-English `# language:`, a second `Feature:` or
`Background:`, a Background after a scenario, steps or tables with nothing to
attach to, unclosed doc strings, rows of different widths, Examples outside an
outline, an outline without Examples, and tags not followed by a Feature,
scenario or Examples.

**Combination rule.** The spec of each scenario is the Background steps
(once, in `background`), then the scenario's own steps, then its Examples
blocks. Consumers (#397) prepend the Background when building a test.

**Tag roles.** With the defaults below:

| Tag | Robot | Gherkin | Role |
| --- | --- | --- | --- |
| Xray test key | `XRay ABC-1`, `XRay:ABC-1`, `XRay=ABC-1` | `@XRay:ABC-1`, `@XRay=ABC-1` | `xray_key` (scenario only) |
| Story key | `Story ABC-1`, `Story:ABC-1`, `Story=ABC-1` | `@Story:ABC-1`, `@Story=ABC-1` | `story_key` |
| Bare key | `ABC-1` | `@ABC-1` | story candidate |
| Manual marker | `manual`, `scaffold` | `@manual`, `@scaffold` | plain; sets `kind: manual` |
| Anything else | `smoke`, `env:prod` | `@smoke`, `@env:prod` | plain, kept whole |

A composite is split only when one side is a configured marker (any case) and
the other an issue key. Every token on a Gherkin tag line must start with `@`,
so `@XRay ABC-1` is rejected; `@XRay @ABC-1` is a plain tag plus a candidate.
There is no Bug role: `@Bug:ABC-9` is plain.

**Scope and precedence.** Feature tags and Robot `Default`/`Test Tags` are
file scope (`inherited`); scenario tags are `local`. The scenario's
`story_key` is its local story key, else the file's explicit story key, else
the file's only bare key; with two or more bare file keys the file story is
`null` and all keys are listed in `story_candidates`. A Gherkin Feature title
bracket (`Feature: [ABC-1] Login`) is used only when the file has no story
key and no candidates. `xray_key` comes only from scenario tags; a file-level
Xray key, or two different Xray or story keys in one scope, is an error.
`effective_plain` is the inherited plus local plain tags; `kind` is `manual`
when any of them is a manual tag, otherwise `cucumber`.

**Configuration.** `XRAY_TEST_TAG` (default `XRay`), `XRAY_STORY_TAG`
(default `Story`) and `XRAY_MANUAL_TAGS` (comma-separated, default
`manual,scaffold`). They load even without `XRAY_DEPLOYMENT`. Each name is
one token without whitespace or `@ : = | ,`, must not look like an issue key,
and names may not collide (case-insensitive).

## Xray tests from test files (#397)

| Tool | Arguments | Result |
| --- | --- | --- |
| `software_delivery.create_xray_tests_from_files` | `files[]` of `{path, content}` (same limits as the preview), `dry_run` (default `false`) | `results[]` (`path`, `line`, `summary`, `status`, `key`, `candidate_keys`, `story_key`, `reason`), `created` (`path::scenario` → key), `dry_run`, `counts`, `stopped`, `stop_reason` |

Creates an Xray test for each scenario without an Xray key tag and links it to
its story. Registered on chat and MCP only when `XRAY_DEPLOYMENT` is
configured; **every call needs approval, including `dry_run`**. The approval
prompt shows the destination (`Jira project QA on jira.example.com`, or
`Jira project QA (Xray Cloud)`), the number of untagged scenarios and up to 10
of them as `file:line · summary` (file name only), each cut to 120 characters,
plus `+N more`. A `dry_run` call is titled "Dry run: plan Xray tests from
files" and says nothing is created. Steps and other file content are never
shown. The result repeats the destination.

Tests always go to `XRAY_PROJECT_KEY`; the story can live in another project.
The read-only `software_delivery.xray_target` tool (no arguments, no approval)
reports that destination and what its project supports, after checking the
project through schema discovery, so the user can confirm it before creating.
To use another project, change `XRAY_PROJECT_KEY` and restart the server.

**Two phases.** The plan phase parses the files, makes every Jira read the
matcher needs (one batched issue lookup, then the tests linked to each story),
matches and builds specs. `dry_run` returns this plan (`WOULD_CREATE` instead of
`CREATED`). The write phase then creates the planned tests one at a time, in
file and line order.

**Statuses.** `CREATED`, `WOULD_CREATE`, `EXISTS_UNTAGGED` (an existing test
was found; tag the file with `key`), `AMBIGUOUS` (several candidates in
`candidate_keys`, or the same story and summary twice in one run), `NO_STORY`
(no story key, story not found, or not one of `XRAY_STORY_ISSUE_TYPES`) and
`ERROR` with a `reason` code.

**Matching** ([`test_files/matching.py`](test_files/matching.py), shared with
#398). A scenario's identity is `path::summary`; a repeated identity, or a
repeated path, is a validation error before any call. A bare key on the
scenario that resolves to a Test is used as that test (`EXISTS_UNTAGGED`)
unless another scenario already claims it. Otherwise the story (local story
key, then the first bare key for Robot; the scenario's `story_key` for Gherkin)
must resolve to an issue whose type name or id is in `XRAY_STORY_ISSUE_TYPES`
and is not a Test. Among the tests linked to the story, only an exact summary
match counts; keys tagged elsewhere in the files, or matched or planned earlier
in the run, are never reused. Steps are never compared.

**Fail closed.** Only Server/DC answers "not found" (HTTP 404). Xray Cloud
looks issues up through `getTests` and `getCoverableIssues` JQL searches, in
chunks of 50 keys and pages of 100, at most 20 pages; a key neither returns is
**unresolved** (`ERROR`), never missing. GraphQL errors on a chunk fall back to
one key at a time; incomplete or malformed pages raise.

**Specs.** The Background is prepended. Manual tests turn `Given`/`When` (and
the `And`/`But` after them) into actions and `Then` (and its `And`/`But`)
into the expected result; a `Then` before any action is
`assertion_without_action`, and a manual outline is
`manual_outline_unsupported`. Cucumber tests keep the steps, data tables and
doc strings with their line, and outlines keep their Examples. Each spec sets
the story as both source and link issue and `XRAY_DEFAULT_COMPONENT` when set.
A project that cannot create the spec as built (manual, Cucumber, outline or
link) gets an `ERROR`; nothing is downgraded.

**Write stop rules.** A definite rejection (`rejected`, `required_fields`)
continues with the next scenario. An outcome that may have written a test
(`outcome_unknown`), a later auth failure (`auth_failed`) or an unconfirmed
link or outline (`link_not_confirmed`, `outline_not_confirmed`, key kept in
`created`) stops the run: the remaining scenarios are `not_attempted`, and
earlier results and keys are kept. An auth failure before anything was created
fails the call.

## Chat-time routing (#312)

Composition injects `WorkflowSignal` probes (see
`composition/chat/workflow_signals.py`) into pack-neutral `TurnRouter`:

| Workflow | Recognized | Ready | Incomplete (clarify, never RAG) |
| --- | --- | --- | --- |
| Test Design | Command phrases (`design tests`, `test design`, …); docs/topical mentions without an Issue locator excluded | Exactly one GitHub Issue locator | Leading command without Issue (#304) |
| Drive export | Clear or partial export/Drive language (docs/prose mentions excluded) | Clear “export … Drive” **and** draft with selected titles **and** agent loop on | Partial phrase (#310); missing titles; agent loop off (`tool_unavailable`) |
| Xray export | Create/export/push/send/upload/publish plus “Xray” (docs/prose mentions excluded) | Draft with generated cases **and** Xray configured with the agent loop on | No generated cases (`missing_fields`); Xray not wired (`tool_unavailable`) |

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
| `software_delivery.test_design_start` | `provider` (one of the providers registered in the deployment: `github`, and `jira` when Jira Data Center is configured) and `locator` (for `github`, an Issue URL or `owner/repo#number`; for `jira`, a key `PROJ-123` or browse URL). Deprecated for one release: `issue_locator` alone, GitHub only (same as `provider: github`) | create draft from the chosen provider's source (#356) |
| `software_delivery.test_design_start_from_text` | `ticket_identifier` (single token, e.g. `PROJ-123`), `title`, `body`, optional `acceptance_criteria`, optional `source_url` (http/https) | create a `client_supplied` draft from content the client already fetched (#355) |
| `software_delivery.test_design_get` | `draft_id` | read draft |
| `software_delivery.test_design_confirm` | `draft_id`, `expected_version`, `candidate_ids` (1 to 40) | patch selection, then confirm |
| `software_delivery.test_design_generate` | `draft_id`, `expected_version`, optional `candidate_ids` (at most 20), optional `test_type` (`manual` or `cucumber`, applied to every generated case), `type_overrides[{candidate_id, test_type}]` (per-candidate exceptions), `overwrite_edited` | #300 generate |
| `software_delivery.test_design_export_feature` | `draft_id` | render the selected, available Cucumber cases as one `.feature` file (`filename`, `content`, `scenario_count`); no model call |

- MCP clients see each tool id with dots replaced by underscores (for example
  `software_delivery_test_design_start`), because clients such as Cursor
  rewrite dotted names. `MCP_TOOL_ALLOWLIST` still takes the dotted ids, and
  calls accept either form.
- The tool descriptions tell the client agent to show the suggested titles and
  let the user choose which to keep, then ask whether one test type applies
  to all of them or the type is chosen per test, before generating. The
  server does not enforce this pause.
- Export returns the file text only; Kernector never writes into the
  client's workspace. The client agent saves `content` where the user
  chooses, so it needs a mode that allows edits.
- `candidate_id` values (`cand-1`, `cand-2`, …) are assigned by the server in
  suggestion order and are keys local to the draft, used only by confirm and
  generate. They are not test-management ids; a later export or sync creates
  those.
- Manual cases carry `steps` and `expected_result`. Cucumber cases leave those
  empty and put their Given/When/Then lines in `gherkin`, with the shared
  `Feature` and `Background` under `cucumber`.
- A generated Cucumber case whose `Examples` table disagrees with its steps
  (no `<placeholder>` used, a column no step reads, or a placeholder with no
  column) is regenerated once with the specific problem. If the retry still
  uses no placeholder, the `Examples` table is dropped so the scenario claims
  only what its literal steps test.

- The `provider` enum in the start tool's schema, and the provider list in its
  description, are built from the registered Test Design sources, so a
  deployment advertises only the trackers it can read. Pass either `provider`
  with `locator`, or `issue_locator` alone; any other combination, or a
  provider that is not registered, returns `validation_error` before any
  workflow call.
- `issue_locator` is deprecated and will be removed after one release. It is
  a GitHub-only alias for `provider: github`: a Jira key or browse URL passed
  as `issue_locator` returns `validation_error` telling the client to retry
  with the provider that accepts it (`unsupported_source` when no registered
  provider does).
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
  `source_not_connected`, `insufficient_evidence`, `unsupported_source` (no
  registered provider accepts the `locator`), otherwise `internal_error`. When
  the chosen provider rejects a `locator` another registered provider accepts,
  the result is `validation_error` with the fixed message "Another connected
  provider accepts this locator; retry with that provider" and no hint.
  `not_found` and `source_not_connected` payloads are identical whichever
  provider was chosen. Nothing is published externally.
- `source_not_connected` payloads also carry
  `"legacy_code": "github_not_connected"` for one release so existing clients
  keep working. Match on `code`; `legacy_code` will be removed.
- Live sources are resolved through the composition-owned Test Design source
  registry (#351). GitHub Issues is always registered and Jira Data Center
  when configured (#353); drafts persist their `source_provider` so confirm
  and generate re-fetch from the same one.

### Live vs client-supplied evidence (#355)

Use `test_design_start` when Kernector is connected to the tracker: it fetches
the Issue live, and confirm and generate re-fetch it, returning
`evidence_changed` if the Issue moved. Use `test_design_start_from_text`
when the client already has the Issue through its own tools (Jira, GitHub or
GitLab MCP servers, `gh`, GraphQL) and Kernector has no connection to that
tracker.

- Every draft result, and the `export_feature` result, carries
  `evidence_origin`: `live` or `client_supplied`. `client_supplied` means
  Kernector did not verify the content against a live source.
- Client-supplied content is rendered once into one canonical evidence text
  ([`test_design/client_evidence.py`](test_design/client_evidence.py)),
  budgeted, and stored with the draft. Confirm and generate reuse it and never
  call a source reader, so the fingerprint cannot change. To change the
  evidence, start a new draft.
- The stored evidence is internal: no MCP result echoes the supplied body,
  acceptance criteria or source URL. Only `evidence_origin` is exposed.
- Supplied content is untrusted input. It goes inside the same defanged
  evidence delimiters as live evidence; `ticket_identifier` must be a single
  token (no whitespace, not a bare number) because it reaches the prompt
  outside those delimiters. Oversized or invalid payloads (title, body,
  acceptance criteria and source URL together over 9,775 characters, URL over
  2,048, unknown fields) return `validation_error` before any workflow call.
  The 9,775 limit is the 10,000-character evidence budget minus the worst-case
  rendering overhead (headings, blank lines and a 160-character ticket line). The combined limit is stated in the tool and
  `body` descriptions, and exceeding it returns a specific message telling the
  client to shorten the body and keep the acceptance criteria. Supplied content
  is never truncated, so acceptance criteria always reach the model in full.
- The tool needs its own `MCP_TOOL_ALLOWLIST` entry; allowlisting
  `test_design_start` does not enable it.

#### Choosing the start tool (#361)

| Scenario | Client tracker tools      | Kernector                                       | Use               |
| -------- | ------------------------- | ----------------------------------------------- | ----------------- |
| 1        | same tracker              | same tracker                                    | `start`           |
| 2        | can read the issue        | not connected, other instance, or no permission | `start_from_text` |
| 3        | none                      | connected                                       | `start`           |
| 4        | wrong project or instance | correct                                         | `start`           |

- Try `test_design_start` first, with the issue's `provider` and the full
  Issue or browse URL as `locator` when you have one. A bare key is read from
  the tracker Kernector is connected to, which may be a different instance
  with the same key. A tracker Kernector has no source for is not in the
  `provider` enum (`validation_error`); a locator another registered provider
  accepts returns `validation_error` asking to retry with that provider; a
  locator no registered provider accepts (for example a browse URL from
  another instance) returns `unsupported_source`.

  ```json
  {"provider": "jira", "locator": "https://jira.example.com/browse/PROJ-123"}
  {"provider": "github", "locator": "https://github.com/acme/app/issues/7"}
  ```
- When `test_design_start` fails with `source_not_connected`, `not_found` or
  `unsupported_source`, the payload carries a fixed `hint` pointing to
  `test_design_start_from_text`, but only when that tool is contributed and
  effective for the caller (allowlisted, pack enabled). Otherwise the payload
  is unchanged, so it reveals nothing about tools the caller cannot use. The
  hint carries no instance URL or provider detail.
- Scenario 4 cannot be detected: when the client fetches the wrong issue with
  its own tools and calls `test_design_start_from_text`, Kernector accepts the
  content unverified. `evidence_origin: client_supplied` is the only signal.
- Decided: a `source_url` on the instance Kernector is connected to gets no
  warning or redirect, because "same instance, Kernector has no permission"
  is a valid `start_from_text` case.
- Decided: no capabilities tool listing the trackers and instances Kernector
  can read. It would reveal connected sources, and the failure hint already
  covers recovery.
