# Capstone package

Assessor entry point for the Kernector Capstone
([#342](https://github.com/mahmoudazaid/Kernector/issues/342)). The Capstone
demonstrates one product path: **Issue → Test Design**. A QA engineer points
Kernector at a GitHub Issue, reviews suggested test coverage, chooses manual or
Cucumber per test, and gets grounded, editable test cases.

| Document | Purpose |
| --- | --- |
| [demo.md](demo.md) | Reproducible local demo runbook and verification note |
| [case-study.md](case-study.md) | Short case study (problem, approach, architecture, data, results, decisions) |
| [presentation.md](presentation.md) | 10-minute talk outline with timing and speaker notes, plus 5-minute Q&A prep |

Setup follows the repository [README](../../README.md). The canonical operator
guide is tracked in [#105](https://github.com/mahmoudazaid/Kernector/issues/105).
[demo.md](demo.md) adds only the Capstone-specific steps.

## Evidence tracker

Status values: **Done**, **In progress**, **Pending**, **Blocked**.

| Deliverable | Status | Evidence | Owner |
| --- | --- | --- | --- |
| Demo link (local, reproducible) | In progress | [demo.md](demo.md); verification note: _add date + commit SHA after a run_ | Author |
| Setup aligned with #105 | Done | [demo.md § Setup](demo.md#setup) points to [README](../../README.md) sections; #105 open | Author |
| Case study | In progress | [case-study.md](case-study.md); evaluation and user-feedback sections TBD | Author |
| Evaluation results | Blocked | [#341](https://github.com/mahmoudazaid/Kernector/issues/341) (open) | #341 |
| User feedback (five QA users) | Blocked | [#343](https://github.com/mahmoudazaid/Kernector/issues/343) (open) | #343 |
| STL assessment | Pending | _add link_ | Author |
| Turing College showcase submission | Pending | _add link_ | Author |
| Presentation (10 min + 5 min Q&A) | Pending | Outline: [presentation.md](presentation.md); recording / slides / attestation: _add link_ | Author |

## Scope

The Capstone covers Issue → Test Design from a GitHub Issue: in Next.js, or
over MCP with client-supplied Issue text. Jira connectors, project memory
([#331](https://github.com/mahmoudazaid/Kernector/issues/331),
[#337](https://github.com/mahmoudazaid/Kernector/issues/337)), and MCP Admin
expansion exist or are planned elsewhere in the repository. None of them is a
Capstone deliverable.
