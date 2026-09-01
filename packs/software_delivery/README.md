# Software Delivery pack

## Requirements analysis (RAG)

Use case: `AnalyzeRequirements` (pack). Presentation calls the typed composition
façade `composition.build_analyze_requirements` → `RequirementsAnalyzer.analyze()`.

Analyzes pasted requirements text against multi-source retrieved evidence and
returns a structured result with `summary`, `acceptance_criteria_gaps`, `risks`,
and `clarification_questions`.

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
)
```

Composition exposes `RequirementsAnalysisView` with the same structured fields.
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
asking for. It is a deterministic keyword policy, not a classifier: a chat-time
tool call is a side effect, and an explicit table is reproducible and testable
offline. Composition reaches it through `registration.build_chat_intent_selector`.

### Input

The raw chat message. It is lowercased and its whitespace collapsed before
matching; nothing else is normalized.

### Output

`ChatToolSelection(generate_tests, output_style)`, or `None` when no Software
Delivery workflow is named — which leaves the query on the ordinary grounded-RAG
path.

### Rules

| Terms | Effect |
|---|---|
| `test case(s)`, `test scenario(s)`, `generate tests`, `write tests`, `test plan`, `acceptance test` | `generate_tests=True` |
| `gherkin`, `given/when/then`, `given when then`, `feature file`, `cucumber` | `generate_tests=True`, `output_style="gherkin"` |
| `risk score`, `score the risk`, `risk assessment`, `assess the risk`, `how risky`, `delivery risk` | `generate_tests=False` |
| anything else | `None` |

- A gherkin term implies generation on its own: "give me a feature file for the
  login story" names a test artifact and needs no second signal.
- Test-generation terms win over risk terms, because the generate chain already
  scores risk first.
- **Declining is the default, and the tables are deliberately narrow.** A false
  negative costs a tool run the user can re-ask for; a false positive runs tools
  nobody wanted. "Can you check the risk here?" does not match, by design.

### Validation

`ChatToolSelection` raises `OrchestrationValidationError` for a non-bool
`generate_tests` or an `output_style` outside `TEST_CASE_STYLES` — the same error
`OrchestrateSoftwareDeliveryRequest` raises for the identical field.
