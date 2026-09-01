# Software Delivery pack

## Requirements analysis (RAG)

Use case: `AnalyzeRequirements` (wired via `composition.build_analyze_requirements` when the pack is enabled).

Analyzes pasted requirements text against multi-source retrieved evidence and returns structured findings (gaps, risks, clarification questions, ambiguities) with trusted provenance.

### Input

```python
AnalyzeRequirementsRequest(requirements="<pasted story or requirements>")
```

Retrieval is injected as `RetrieveEvidence = Callable[[str], Sequence[ScoredChunk]]` — one query argument, **no metadata filter channel**, so the pack cannot narrow retrieval to a single source kind.

Composition binds `RewriteAndRetrieveKnowledge` behind that callable, applies `settings.retrieval.relevance_threshold`, and passes `settings.retrieval.limit` as top-k. Unsafe override attempts in the requirements text may surface as `ApplicationValidationError` from the rewrite-and-retrieve path before the pack runs.

### Output

```python
RequirementsAnalysisResult(
    answer="...",
    findings=(
        RequirementsFinding(category="gap", statement="...", references=(...)),
        ...
    ),
    evidence=(<ScoredChunk>, ...),  # cited chunks in retrieval-rank order
)
```

`evidence` carries domain `ScoredChunk` values (not `application.contracts.Citation`) because packs may not import application types. Composition projects citations via `analysis_citations(result)`.

### Model JSON contract

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
| `ToolFailureError` | Provider failure or invalid model JSON / evidence ids |

Named budgets: `MAX_REQUIREMENTS_CHARS`, `MAX_TOTAL_INPUT_CHARS`, `MAX_MODEL_RESPONSE_CHARS`, `MAX_ANALYSIS_ANSWER_CHARS`, `MAX_ANALYSIS_FINDINGS`, `MAX_FINDING_STATEMENT_CHARS`, `REQUIREMENTS_ANALYSIS_MODEL_SETTINGS`.

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
