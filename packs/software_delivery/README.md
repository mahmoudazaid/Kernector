# Software Delivery pack

## Requirements analysis (RAG)

Use case: `AnalyzeRequirements` (pack). Chat routes through the pack intent
policy (`analyze|review … requirements|story`) into
`composition.build_analyze_requirements` → `RequirementsAnalyzer.analyze()`,
and `ToolAugmentedAsk` formats the view into an `AskResponse`.

Analyzes requirements text (pasted in chat after an analysis cue) against
multi-source retrieved evidence and returns a structured result with `summary`,
`acceptance_criteria_gaps`, `risks`, and `clarification_questions`.

### Input

```python
AnalyzeRequirementsRequest(requirements="<pasted story or requirements>")
```

Retrieval is injected as `RetrieveEvidence = Callable[[str], Sequence[ScoredChunk]]` — one query argument, **no metadata filter channel**, so the pack cannot narrow retrieval to a single source kind.

Composition binds `RewriteAndRetrieveKnowledge` behind that callable, applies `settings.retrieval.relevance_threshold`, and passes `settings.retrieval.limit` as top-k. Unsafe override attempts in the requirements text may surface as `ApplicationValidationError` from the rewrite-and-retrieve path before the pack runs.

### Output

```python
RequirementsAnalysisResult(
    summary="...",
    acceptance_criteria_gaps=(RequirementsFinding(statement="...", references=(...)), ...),
    risks=(...),
    clarification_questions=(...),
    evidence=(<ScoredChunk>, ...),  # cited chunks in retrieval-rank order
    ask_result=<AskResult>,  # model-call metadata; projected to AskResponse.run
)
```

Composition exposes `RequirementsAnalysisView` with the same structured fields plus
optional ``ask_result``. Chat-time analysis projects that metadata to
``RunMeta`` on ``AskResponse.run`` without changing the model JSON contract below.
`evidence` carries domain `ScoredChunk` values (not `application.contracts.Citation`) because packs may not import application types. Composition projects citations via `analysis_citations(view)`.

### Model JSON contract

```json
{
  "summary": "...",
  "acceptance_criteria_gaps": [{"statement": "...", "evidence_ids": ["e0"]}],
  "risks": [],
  "clarification_questions": []
}
```

All four top-level fields are required. Individual sections may be empty arrays.
The model cites evidence with catalog ids `e0`, `e1`, … matching the ordered evidence array inside the untrusted assessment block. Findings must not supply their own `references` — provenance is resolved from the catalog the pack built from retrieval hits.

### Rules

- Requirements and retrieved evidence share one untrusted user region via `build_assessment_prompt` (`target=` is the requirements text).
- Trusted analysis instructions stay in `system`.
- `evidence` on the result is derived from raw retrieval hits, never from model text.

### Validation

| Failure | When |
|---|---|
| `RequirementsAnalysisValidationError` | Invalid or over-budget caller input / prompt before retrieval or the model |
| `MissingEvidenceError` | No hits after retrieval (including below relevance threshold) |
| `ProviderError` | Propagated unchanged from `ChatModel.complete()` |
| `RequirementsAnalysisOutputError` | Invalid model JSON, schema violations, unknown evidence ids, or unusable model output |

Named budgets: `MAX_REQUIREMENTS_CHARS`, `MAX_TOTAL_INPUT_CHARS`, `MAX_MODEL_RESPONSE_CHARS`, `MAX_ANALYSIS_SUMMARY_CHARS`, `MAX_FINDINGS_PER_SECTION`, `MAX_FINDING_STATEMENT_CHARS`, `REQUIREMENTS_ANALYSIS_MODEL_SETTINGS`.

When every finding section is empty, `evidence` retains all threshold-cleared retrieval hits as supporting context for the summary. When any section contains findings, `evidence` includes only chunks referenced by those findings.

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

`ChatToolSelection(generate_tests, output_style, analyze_requirements=False,
analysis_target="")`, or `None` when no Software Delivery workflow is
explicitly named — which leaves the query on the ordinary grounded-RAG path.

### Rules

| Requirement | Effect |
|---|---|
| Same-clause creation → artifact | `generate_tests=True`, `output_style="steps"` unless a gherkin-style term appears anywhere in the query |
| Creation verbs | `create`, `generate`, `write`, `produce`, `draft`, `build` |
| Allowed between verb and artifact | optional article (`a`/`an`/`the`/`some`/`more`), optional adjective (`comprehensive`/`detailed`/`new`), optional style (`gherkin`/`cucumber`/`given/when/then`/`given when then`) |
| Test artifacts | `test case(s)`, `test scenario(s)`, `tests`, `scenarios`, `acceptance test(s)`, `test plan`, `feature file(s)`, `cucumber scenario(s)` |
| Gherkin-style terms (with a matched generation request) | `output_style="gherkin"` when `gherkin`, `cucumber`, `given/when/then`, `given when then`, or `feature file` appears |
| Explicit requirements analysis | `analyze_requirements=True` with `analysis_target` = text after the cue — e.g. `Analyze these requirements: …`, `Review this story: …`, `Analyze requirements for AUTH-101` |
| Explicit risk requests | `generate_tests=False` — e.g. `assess/score/evaluate the risk`, `what is the risk score for <target>`, `how risky is <target>`, `risk assessment of <target>` |
| Intent-local negation | Cancels only the governed match — `Do not create test cases`, `Never generate tests`, `Do not assess the risk`, `Do not analyze these requirements`. Constraint wording (`that do not require…`) and other-clause negation (`…; never use…`) do not cancel. Mixed requests keep the active intent (`Do not generate tests; assess the risk` → risk-only). |
| How-to / conceptual | `None` — e.g. `How do I create test cases?`, `How to write Gherkin scenarios`, `Explain how to generate tests`, `What is Gherkin?`, `How do I analyze requirements?` |
| Read-only transforms | `None` — e.g. `Create a summary/list/overview of the existing test cases`, `Generate a report without creating tests`, `Create a summary, not test cases` |
| Distant verb∩artifact co-occurrence | `None` — independent substring presence is not enough |
| Artifact or style term alone | `None` — `gherkin`, `cucumber`, `feature file`, `test plan`, and `test cases` need a bound creation verb |
| Analysis cue alone | `None` — `Analyze these requirements` with no body after the cue |

- Test-generation requests win over analysis and risk terms, because the generate
  chain already scores risk first.
- Requirements analysis wins over risk-only when both would match.
- **Declining is the default, and the tables are deliberately narrow.** A false
  negative costs a tool run the user can re-ask for; a false positive runs tools
  nobody wanted. "Can you check the risk here?" does not match, by design.

### Validation

`ChatToolSelection` raises `OrchestrationValidationError` for a non-bool
`generate_tests` / `analyze_requirements`, an `output_style` outside
`TEST_CASE_STYLES`, mutually exclusive flags, or a blank `analysis_target` when
analysis is selected — the same error family
`OrchestrateSoftwareDeliveryRequest` raises for overlapping fields.
