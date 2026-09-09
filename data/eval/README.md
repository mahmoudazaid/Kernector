# Offline RAG and tool eval dataset

Curated corpus and cases for GitHub issue #102. The harness is **unconditionally offline**: it never reads `OPENROUTER_API_KEY`, never calls OpenRouter or Ollama, and always records `mode: offline`.

## Command

```bash
uv run python -m presentation.cli.evaluate [--output DIR]
```

Default `--output` is `output/eval`. The command writes `eval-report.json` and `eval-report.md`. Do not commit generated reports.

## Dataset

| File | Role |
| --- | --- |
| `corpus.json` | Small BM25 documents (single-source, overlapping cross-source, conflicting SLA pair, novel `future-connector`). There is no irrelevant-only document. |
| `cases.json` | One case per required class: `single_source`, `cross_source`, `irrelevant`, `conflicting`, `unknown_source_kind`, `citation_provenance`, `pack_off`, `tool`. |

`schema_version` is `kernector.eval.v1`.

The irrelevant case uses a query with no lexical overlap so BM25 returns no evidence. The pack-off query is risk-shaped (`assess the risk of checkout`) while packs stay disabled. The tool case invokes `software_delivery.risk_score` with a worked evidence bundle (`level` `high`, `score` `60`).

## Skip reasons

Coverage marks a class `skipped` only when:

- `no_case_configured` — the suite has no case of that class
- `tool_unavailable` — invoke_tool cases existed but `InvokeTool` could not be wired after a pack-on Settings copy

Missing live credentials never skip a case and never change `mode`.
