# Offline RAG and tool eval dataset

Curated corpus and cases for GitHub issues #102 and #106.

The default command is **unconditionally offline** (`--judge-mode off`): it never reads `OPENROUTER_API_KEY` to choose behavior, never calls OpenRouter or Ollama, and always records `mode: offline` on `kernector.eval.v1`.

`--judge-mode live` is a separate quality path. It still writes the #102 JSON/Markdown reports, then also runs configured RAG on a **temporary Chroma** copy of this eval corpus (never `data/chroma`) and scores `kind=ask` cases with an independent Judge model (`RAG_JUDGE_*`).

## Command

```bash
uv run python -m presentation.cli.evaluate [--output DIR] [--judge-mode off|live|fake|auto]
```

Default `--output` is `output/eval`. Default `--judge-mode` is `off`.

| Mode | Writes |
| --- | --- |
| `off` | `eval-report.json`, `eval-report.md` |
| `live` / `fake` / `auto` | those files **plus** `rag-judge-report.json` and `rag-judge-report.csv` |

`auto` runs live only when answer RAG and Judge config are both valid. It never substitutes fake scores. Do not commit generated reports.

## Answer model versus Judge model

Two distinct calls. Never conflate them.

1. **Answer model under test** — `LLM_PROVIDER` / `OPENROUTER_MODEL` or Ollama. Generates the visible RAG answer. A live quality run that uses `DeterministicChatModel` as the answer model is invalid.
2. **Judge model** — `RAG_JUDGE_PROVIDER` + `RAG_JUDGE_MODEL` only. Scores the already-generated answer. Prompt version: `kernector.rag-judge.prompts.v1`.

`--judge-mode off` still uses `DeterministicChatModel` for the #102 offline report. That path is not a live quality gate.

Judge scores are model opinions, not ground truth.

## Dataset

| File | Role |
| --- | --- |
| `corpus.json` | Small documents (single-source, overlapping cross-source, conflicting SLA pair, novel `future-connector`, Software Delivery `user_story`/`srs`). There is no irrelevant-only document. |
| `cases.json` | Required #102 classes plus Judge-eligible grounded ask rows (`reference_answer`, optional `slice`). |
| `schema/` | Strict JSON Schemas for Judge reports, baselines, and ask-case extensions. |
| `baselines/rag-judge-baseline.json` | Unaccepted placeholder until a live human review. `allowed_drop` here is advisory; gate tolerance is caller/policy-owned and recorded on the Judge report. |
| `human_review.md` | DoD live-review record (not filled by pytest). |

`schema_version` for the offline suite is `kernector.eval.v1`. Judge reports use `kernector.rag-judge.v1`.

Ask cases are the only Judge-eligible kind. `retrieve`, `pack_off`, and `invoke_tool` stay on the offline harness and are never Judged. The Software Delivery ask (`sd-password-reset-ask`) asks how long a password-reset email code is valid; it is not pack-shaped (no “assess the risk” / generate-tests).

The irrelevant case uses a query with no lexical overlap so BM25 returns no evidence. The pack-off query is risk-shaped (`assess the risk of checkout`) while packs stay disabled. There is no `invoke_tool` case while the Software Delivery registry is empty (#285). The `tool` class is not required until a real tool lands; offline eval exits `0`.

## Skip reasons

Coverage marks a class `skipped` only when:

- `no_case_configured` — the suite has no case of that class
- `tool_unavailable` — the injected `invoke` seam is absent. Composition always
  wires `InvokeTool`, so this cannot occur through the CLI; it exists for callers
  that construct `EvaluateKnowledge` with `invoke=None`.

The CLI exits `1` when any required class is skipped with `no_case_configured`.
`tool` is optional until restored with the first real tool under
`packs/software_delivery/tools/` (#285).

Missing live credentials never skip a #102 case and never change `mode`. `--judge-mode auto` without ready Judge/answer config is a loud skip (exit `2`), not a fake run.
