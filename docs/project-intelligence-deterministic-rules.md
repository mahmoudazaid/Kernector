# Deterministic reference matching rules (#375)

Canonical `rule_id` values are stored on relationship evidence as
`EvidenceRef.extractor_id`.

| Rule id | Subject kinds / contexts | Relation | Notes |
| --- | --- | --- | --- |
| `key_mention.tag` | `automated_test` | `automates` | Robot `[Tags]`, Gherkin `@KEY`, pytest markers, Playwright title `@KEY` |
| `key_mention.header` | `code_file` | `references` | File header / module docstring; never `implements` |
| `key_mention.doc` | `document` | `describes` | Key mention in documentation |
| `api_operation.mention` | any mentioning artifact | by context matrix | Exact `operationId` or normalized `METHOD /path` |

## API mention context matrix

| Subject context | Relation |
| --- | --- |
| `business`, `frontend`, `backend`, `operations` | `references` |
| `testing` | `exercises` |
| `documentation` | `describes` |

Unknown project keys are ignored. An API identity absent from the current
project contract yields an `unresolved_operation` diagnostic only.
