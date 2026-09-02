# Software Delivery pack

## Markdown test-case export

Tool: `software_delivery.export_test_cases_markdown`

Exports structured test cases and their source citations as Markdown. The output contains generated cases and citations only — no objectives, strategy, coverage summaries, scope, or entry/exit criteria.

### Input

Same shape as the JSON output from `software_delivery.generate_test_cases`:

```json
{
  "output_style": "steps",
  "test_cases": [{
    "title": "...",
    "steps": ["..."],
    "expected": "...",
    "references": [{"source_id": "...", "source_type": "..."}]
  }]
}
```

### Output template

```markdown
# Test Cases

**Output style:** {output_style}

## {n}. {title}

### Steps

{numbered list when output_style is steps | bullet list when gherkin}

### Expected result

{expected}

### References

- `{source_id}` ({source_type})
```

### Formatting rules

- One root `output_style` per export (`steps` or `gherkin`)
- Case order preserved from input
- References sorted by `(source_type, source_id)` as normalized by `GeneratedTestCase`
- Single trailing newline at EOF
- Heading levels: `#` document, `##` case, `###` section

### Validation

Invalid or empty input raises `MarkdownExportValidationError` before any Markdown is produced.

## Chat-time intent selection

`select_chat_intent(query)` decides which tool chain — if any — a chat message is
asking for. It is a deterministic explicit-request policy, not a classifier.
Composition reaches it through `registration.build_chat_intent_selector`.
**Only General chat** (`AskRequest.prompt_key is None`) is eligible; selected
task prompts always stay on grounded RAG and never reach this policy.

### Input

The raw chat message. It is lowercased, apostrophes normalized (`don't` →
`dont`), and whitespace collapsed before matching; nothing else is normalized.

### Output

`ChatToolSelection(generate_tests, output_style)`, or `None` when no Software
Delivery workflow is explicitly named — which leaves the query on the ordinary
grounded-RAG path.

### Rules

| Requirement | Effect |
|---|---|
| Same-clause creation → artifact | `generate_tests=True`, `output_style="steps"` unless a gherkin-style term appears anywhere in the query |
| Creation verbs | `create`, `generate`, `write`, `produce`, `draft`, `build` |
| Allowed between verb and artifact | optional article (`a`/`an`/`the`/`some`/`more`), optional adjective (`comprehensive`/`detailed`/`new`), optional style (`gherkin`/`cucumber`/`given/when/then`/`given when then`) |
| Test artifacts | `test case(s)`, `test scenario(s)`, `tests`, `scenarios`, `acceptance test(s)`, `test plan`, `feature file(s)`, `cucumber scenario(s)` |
| Gherkin-style terms (with a matched generation request) | `output_style="gherkin"` when `gherkin`, `cucumber`, `given/when/then`, `given when then`, or `feature file` appears |
| Explicit risk requests | `generate_tests=False` — e.g. `assess/score/evaluate the risk`, `what is the risk score for <target>`, `how risky is <target>`, `risk assessment of <target>` |
| Intent-local negation | Cancels only the governed match — `Do not create test cases`, `Never generate tests`, `Do not assess the risk`. Constraint wording (`that do not require…`) and other-clause negation (`…; never use…`) do not cancel. Mixed requests keep the active intent (`Do not generate tests; assess the risk` → risk-only). |
| How-to / conceptual | `None` — e.g. `How do I create test cases?`, `How to write Gherkin scenarios`, `Explain how to generate tests`, `What is Gherkin?` |
| Read-only transforms | `None` — e.g. `Create a summary/list/overview of the existing test cases`, `Generate a report without creating tests`, `Create a summary, not test cases` |
| Distant verb∩artifact co-occurrence | `None` — independent substring presence is not enough |
| Artifact or style term alone | `None` — `gherkin`, `cucumber`, `feature file`, `test plan`, and `test cases` need a bound creation verb |

- Test-generation requests win over risk terms, because the generate chain
  already scores risk first.
- **Declining is the default, and the tables are deliberately narrow.** A false
  negative costs a tool run the user can re-ask for; a false positive runs tools
  nobody wanted. "Can you check the risk here?" does not match, by design.

### Validation

`ChatToolSelection` raises `OrchestrationValidationError` for a non-bool
`generate_tests` or an `output_style` outside `TEST_CASE_STYLES` — the same
error family `OrchestrateSoftwareDeliveryRequest` raises for overlapping fields.
