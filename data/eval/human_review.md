# RAG LLM-as-Judge human review

This file records the #106 Definition of Done live review. Pytest stays offline and must not fill this in.

An accepted baseline may be created **only** from a reviewed live run. The committed placeholder in `baselines/rag-judge-baseline.json` is unaccepted until this review exists.

## Run

- Date:
- Reviewer:
- Run ID / output directory:
- Answer model (provider / model):
- Judge model (provider / model):
- Prompt version: `kernector.rag-judge.prompts.v1`

## Sampled case IDs

- 

## Metric disagreements

| Case ID | Metric | Judge score | Human decision | Notes |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Decisions

- [ ] Live run used configured RAG on a temp eval Chroma corpus (not `data/chroma`)
- [ ] Answer model was not `DeterministicChatModel`
- [ ] Judge model was distinct from the answer model
- [ ] Sample reviewed; disagreements recorded
- [ ] Initial accepted baseline created from this run only

Gate regression tolerance (`allowed_drop`) is **caller/policy-owned**. The baseline file still records an `allowed_drop` for review context, but it does not change the gate; the effective value is written on `rag-judge-report.json`.

## Limitations

Judge scores are model opinions, not ground truth. Metrics do not replace human review.
