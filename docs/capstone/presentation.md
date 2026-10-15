# Capstone presentation: 10 minutes + 5 minutes Q&A

Outline for the timed STL and Turing College showcase presentation
([#342](https://github.com/mahmoudazaid/Kernector/issues/342)). Content is
drawn from [case-study.md](case-study.md). The live demo follows
[demo.md](demo.md) Path A.

Record the delivered talk (recording, slides export, or assessor attestation)
in the [evidence tracker](README.md#evidence-tracker).

## Timing

| # | Slide | Start | Length |
| --- | --- | --- | --- |
| 1 | Title and one-line pitch | 0:00 | 0:30 |
| 2 | The QA job and the problem | 0:30 | 1:00 |
| 3 | Current alternatives | 1:30 | 0:45 |
| 4 | Approach: live evidence, human in the loop | 2:15 | 1:00 |
| 5 | Live demo: Issue → Test Design | 3:15 | 3:30 |
| 6 | Architecture and data handling | 6:45 | 1:15 |
| 7 | Evaluation and user feedback | 8:00 | 0:45 |
| 8 | Hardest decision and next steps | 8:45 | 1:15 |
| | **End of talk** | **10:00** | |
| | Q&A | 10:00 | 5:00 |

## Slides and speaker notes

### 1. Title (0:30)

- Kernector: from a GitHub Issue to reviewed, grounded test cases.
- Notes: name, role, one sentence. "QA engineers turn Issues into tests by
  hand. Kernector drafts that coverage from the live Issue, with the engineer
  deciding what to keep."

### 2. The QA job and the problem (1:00)

- Every Issue needs a decision about what to test, then written cases.
- Evidence is scattered, the work is repetitive, and cases drift from the
  Issue.
- Notes: use one concrete Issue as the running example (the same one used in
  the demo).

### 3. Current alternatives (0:45)

- Manual authoring in spreadsheets, Xray, or `.feature` files: slow and
  untraceable.
- Pasting into a generic chatbot: fast, but ungrounded and unreviewed.

### 4. Approach (1:00)

- Read the Issue live; never generate from a stale index.
- Two steps: the model suggests, the engineer selects (manual or Cucumber per
  test), then cases are generated.
- Fail closed when the Issue changed; never overwrite user edits.
- Same workflow in the web app and over MCP in Cursor or Claude Code.

### 5. Live demo (3:30)

Run [demo.md](demo.md) Path A with the stack already started and GitHub
already connected:

1. `/chat`: "design tests <Issue URL>", then **Start Test Design** (0:45).
2. **Test selection**: drop one candidate, add one, set one test to Cucumber,
   then **Next** (1:15).
3. **Test steps**: show a manual case and the Cucumber Feature; edit one step
   and show **Saved** (1:00).
4. Point out that each case traces back to the Issue (0:30).

Backup: if the network or the provider fails, play a pre-recorded clip of the
same run. Keep it linked in the evidence tracker.

### 6. Architecture and data handling (1:15)

- Domain-agnostic core; Test Design lives in the Software Delivery pack;
  composition is the only wiring root (show the architecture image).
- Tokens stay on the server, evidence is treated as untrusted input, model
  output is labeled, and logs carry metadata only.

### 7. Evaluation and user feedback (0:45)

- Evaluation: results from
  [#341](https://github.com/mahmoudazaid/Kernector/issues/341). Until it
  lands, say so plainly and show the evaluation plan, not numbers.
- Users: findings from
  [#343](https://github.com/mahmoudazaid/Kernector/issues/343). Until it
  lands, say so plainly.

### 8. Hardest decision and next steps (1:15)

- Decision: keep the core domain-agnostic and put Test Design in a pack.
  Cost: more wiring. Payoff: a second tracker and a second front door (MCP)
  without forking the workflow.
- Next: evaluation baseline (#341), user-study fixes (#343), public Issues
  without a connection (#302).
- Close with the one-line pitch.

## Q&A prep (5:00)

| Likely question | Short answer |
| --- | --- |
| How do you know the generated tests are good? | The coverage-quality evaluation is #341. Until it lands, the human selection step is the quality gate, and I don't claim numbers. |
| What stops the model from inventing behavior? | Cases are generated only from the Issue text, which is wrapped as untrusted evidence. The engineer reviews candidates before any cases exist, and Issues without enough evidence come back as "needs clarification". |
| What happens if the Issue changes? | Generate re-reads the Issue and compares a fingerprint. On a mismatch, it stops without writing. |
| Why not just use RAG over all your documents? | Test Design needs the current Issue, not the closest chunk. Live reads make change detection possible. RAG still powers cited chat. |
| Why MCP? | Engineers already work in Cursor or Claude Code. MCP lets that assistant drive the same workflow instead of a second chatbot. |
| How are credentials protected? | OAuth grants stay on the server in gitignored files. The browser and MCP results never receive tokens, and logs exclude content and secrets. |
| Does it work with Jira? | Jira is not a Capstone deliverable. The source registry is tracker-neutral, so other trackers plug in as adapters. |
| What was hardest? | Keeping the core free of ticket vocabulary while shipping a ticket-centric feature. See slide 8. |
| What would you do with more time? | Evaluation baseline, user-study fixes, and public Issues without a connection. |
