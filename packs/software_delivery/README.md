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
| `ToolFailureError` | Invalid model JSON, schema violations, unknown evidence ids, or unusable model output |

Named budgets: `MAX_REQUIREMENTS_CHARS`, `MAX_TOTAL_INPUT_CHARS`, `MAX_MODEL_RESPONSE_CHARS`, `MAX_ANALYSIS_SUMMARY_CHARS`, `MAX_FINDINGS_PER_SECTION`, `MAX_FINDING_STATEMENT_CHARS`, `REQUIREMENTS_ANALYSIS_MODEL_SETTINGS`.

## Markdown test-case export
