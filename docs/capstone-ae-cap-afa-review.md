# Capstone (AE.CAP_afa.md) — Requirements Review

**Project:** Kernector  
**Spec:** [`AE.CAP_afa.md`](../AE.CAP_afa.md)  
**Prior sprint:** [`sprint-3-135-review.md`](sprint-3-135-review.md)  
**Review date:** 2026-10-16  
**Chosen path:** Alternative idea, closest to **Case 2 (AI agent for task automation)**, scoped as Issue → Test Design ([#342](https://github.com/mahmoudazaid/Kernector/issues/342)). Case 1 (RAG assistant) and Case 3 (document search) are already in the product and support that path. Cases 4–7 are out of scope.  
**Verdict:** **Product path is built. Shared review criteria are not fully ready.** Functionality, UI, the README problem paragraph, the showcase link, LangChain/LangGraph, Chroma, and LLM APIs are in place. Evaluation numbers ([#341](https://github.com/mahmoudazaid/Kernector/issues/341)), five-user feedback ([#343](https://github.com/mahmoudazaid/Kernector/issues/343)), a named ethics write-up (privacy is documented; bias mitigation is not), and a delivered presentation are still open.

---

## Summary

| Area | Count |
|------|-------|
| Shared criteria Ready | 3 / 5 |
| Shared criteria Partial | 2 / 5 |
| Shared criteria Not done | 0 / 5 |
| Case 2 steps Done | 4 / 6 |
| Case 2 steps Partial | 2 / 6 |
| Case 1 (supporting) | 3 Done / 3 Partial |
| Case 3 (supporting) | 4 Done / 0 Partial |
| Cases 4–7 | Not the chosen path |
| Capstone package | [`docs/capstone/`](capstone/README.md) ([#342](https://github.com/mahmoudazaid/Kernector/issues/342)) |

**Framing:** The brief asks for one case, or an alternative that still meets the shared criteria. Kernector’s assessor path is **Issue → Test Design**: a QA engineer points at a GitHub Issue or a Jira issue, reviews suggested coverage, chooses manual or Cucumber per test, and gets grounded, editable cases. Those cases can be exported as a file or created as Xray tickets. The same workflow runs in Next.js and over MCP. Live issue reads, human selection, and fail-closed regeneration are the capstone behaviors. Grounded RAG chat, Chroma retrieval, and the LangGraph tool loop are the learning-application evidence underneath that path.

**Entry (current):**

```bash
HTTP_DEV_CORS=true DOMAIN_TOOL_PACKS=software-delivery \
  uv run uvicorn presentation.http.app:app --reload
cd web && npm run dev   # http://localhost:3000
```

Demo runbook: [`docs/capstone/demo.md`](capstone/demo.md). Case study: [`docs/capstone/case-study.md`](capstone/case-study.md). Talk outline: [`docs/capstone/presentation.md`](capstone/presentation.md).

---

## Shared evaluation criteria

These apply to every case in [`AE.CAP_afa.md`](../AE.CAP_afa.md).

| Requirement | type | status | location | left | ticket |
|---|---|---|---|---|---|
| Outcome quality: working project, usable UI, README states goal, problem, and how it works | Outcome | Done | Next.js UI is live (`web/app/chat`, `/test-design`, `/documents`). Root [`README.md`](../README.md) opens with the goal, the QA problem, and how Issue → Test Design works | — | [#342](https://github.com/mahmoudazaid/Kernector/issues/342) |
| Learning application: LangChain, ChromaDB, or LLM APIs, plus prompt and design practice | Learning | Done | LangGraph agent (`infrastructure/agents/langgraph_tool_agent.py`), Chroma (`infrastructure/vectorstore/chroma.py`, `CHROMA_PERSIST_PATH`), OpenRouter/Ollama (`infrastructure/config.py`). Prompts by role ([ADR 0009](adr/0009-prompt-storage-by-role.md)); untrusted-evidence wrapping (`application/untrusted_text.py`); grounded ask | — | Sprint 2/3 carryover; [#43](https://github.com/mahmoudazaid/Kernector/issues/43), [#216](https://github.com/mahmoudazaid/Kernector/issues/216) |
| Ethical considerations: privacy and bias called out in the project write-up | Ethics | Partial | Privacy is implemented and written in [`case-study.md`](capstone/case-study.md) §5: server-side OAuth, untrusted evidence, `untrusted_model_output`, metadata-only logs, workspace isolation (`application/input_safety.py`) | A write-up of bias mitigation: human selection before cases are written, generation from the issue text only, and refusal when the issue lacks evidence | [#342](https://github.com/mahmoudazaid/Kernector/issues/342) |
| Presentation: purpose, implementation, impact, using SCR or SMART; six talk points | Presentation | Partial | [`presentation.md`](capstone/presentation.md) covers the six brief points with timing. The case study follows Situation / Complication / Resolution | Deliver the 10 + 5 talk and record it in the [evidence tracker](capstone/README.md#evidence-tracker). Name SCR or SMART in the write-up. Fill slide 7 after [#341](https://github.com/mahmoudazaid/Kernector/issues/341) and [#343](https://github.com/mahmoudazaid/Kernector/issues/343) | [#342](https://github.com/mahmoudazaid/Kernector/issues/342) |
| Showcase upload and link near the top of `README.md` | Showcase | Done | Published 2026-10-16, status Live. Linked under the title in [`README.md`](../README.md): [Kernector: reviewed test cases from user story](https://showcase.turingcollege.com/project/4c183de0-867c-470c-9bd2-ded181fc15a7) | — | [#342](https://github.com/mahmoudazaid/Kernector/issues/342) |

---

## Case 2 — AI agent for task automation (chosen path)

**Objective in the brief:** an agent that automates a real workflow, with tools, multi-step execution, a live UI, an evaluation, and a report that includes ethics.

Kernector’s workflow is test design from a live GitHub Issue or Jira issue, with the engineer in the loop, then a file export or Xray tickets. That matches the brief’s “alternative ideas are valid” clause and Case 2’s steps.

| Step | status | location | left | ticket |
|---|---|---|---|---|
| 1. Agent design: purpose, capabilities, target users | Done | Capstone job and approach in [`case-study.md`](capstone/case-study.md) §1–3. Users: QA / engineering on delivery teams | — | [#342](https://github.com/mahmoudazaid/Kernector/issues/342) |
| 2. Tool integration: APIs, data access, external systems | Done | GitHub and Jira live reads, Test Design MCP tools (`packs/software_delivery/tools/`), `.feature` file export, Xray test creation, Google Drive export with approval | — | [#338](https://github.com/mahmoudazaid/Kernector/issues/338), [#353](https://github.com/mahmoudazaid/Kernector/issues/353), [#423](https://github.com/mahmoudazaid/Kernector/issues/423), [#199](https://github.com/mahmoudazaid/Kernector/issues/199) |
| 3. Agent execution: multi-step reasoning, memory, or code execution | Done | The brief asks for one of the three. Multi-step Test Design (suggest → human select → generate) and the opt-in LangGraph loop meet it. Short-term thread memory is also in place (`InMemorySaver`) | — | [#43](https://github.com/mahmoudazaid/Kernector/issues/43), [#213](https://github.com/mahmoudazaid/Kernector/issues/213) |
| 4. Interactive prototype (Streamlit or another UI) | Done | Next.js chat, Test Design screens, Knowledge Hub. Case 2 allows another interface. Second front door: MCP | — | [#126](https://github.com/mahmoudazaid/Kernector/issues/126), [#338](https://github.com/mahmoudazaid/Kernector/issues/338) |
| 5. Evaluation: accuracy and responsiveness via user testing | Partial | RAG offline harness + LLM-as-Judge (`presentation/cli/evaluate.py`, [`data/eval/README.md`](../data/eval/README.md)) score grounded ask only | Test Design coverage baseline ([#341](https://github.com/mahmoudazaid/Kernector/issues/341)) written into case study §6, and a five-QA-user study ([#343](https://github.com/mahmoudazaid/Kernector/issues/343)) written into §7 | [#341](https://github.com/mahmoudazaid/Kernector/issues/341), [#343](https://github.com/mahmoudazaid/Kernector/issues/343) |
| 6. Documentation: functionality and ethical considerations | Partial | Functionality is in [`case-study.md`](capstone/case-study.md), [`demo.md`](capstone/demo.md), and [`ARCHITECTURE.md`](../ARCHITECTURE.md). Privacy is in case study §5 | The bias-mitigation section called out under Ethics above | [#342](https://github.com/mahmoudazaid/Kernector/issues/342) |

**Case 2 outcome the brief asks for:** a practical agent that automates a task and can be demoed. The Issue → Test Design path meets that, once a verified demo note is filled in [`demo.md`](capstone/demo.md) (date, commit, Issue used).

---

## Case 1 — RAG knowledge assistant (supporting, already built)

| Step | status | location | left |
|---|---|---|---|
| 1. Data preparation and embeddings | Done | Uploads, seed JSON, Drive, GitHub, Jira → chunk → embed (`composition/container.py`, OpenRouter embeddings) | — |
| 2. Vector database | Done | Chroma persist path; hybrid BM25 + vector when enabled | — |
| 3. LangChain RAG chain | Done | Grounded ask plus agentic retrieve (`RetrieveKnowledgeTool`, `AskKnowledgeWithAgent`) | — |
| 4. Streamlit UI | Partial | Interactive UI is Next.js | A Streamlit UI, only if Case 1 is the graded case. The chosen path uses Next.js, which Case 2 allows |
| 5. Testing and optimisation | Partial | Offline + judge harness for grounded ask | Test Design coverage evaluation ([#341](https://github.com/mahmoudazaid/Kernector/issues/341)) |
| 6. Ethical assessment (privacy and bias) | Partial | Privacy controls exist and are described in case study §5 | The same bias-mitigation write-up as the shared Ethics row |

Claim Case 1 only as supporting evidence. The graded story in `docs/capstone/` is the agent workflow.

---

## Case 3 — Smart document search (supporting, already built)

| Step | status | location |
|---|---|---|
| 1. Document ingestion | Done | PDF/TXT/Markdown upload, connectors, catalog |
| 2. Semantic search | Done | Embeddings + Chroma similarity, optional hybrid fusion |
| 3. Contextual responses | Done | Grounded ask with citations in Next.js chat |
| 4. UI to upload and query | Done | `web/app/documents`, `web/app/chat` |

Case 3’s outcome is met by Knowledge Hub + cited chat. It is not the capstone narrative.

---

## Cases 4–7 (not chosen)

| Case | status | notes |
|---|---|---|
| 4. Multi-modal (image, DALL·E, CLIP, Whisper) | Not in scope | No image caption, cross-modal search, or image generation path |
| 5. Code generation and debugging IDE | Not in scope | MCP exposes Test Design tools to coding assistants. Kernector does not generate or debug arbitrary code, and it is not an IDE |
| 6. Deeper-topic notes | Not in scope | The submission is a built product, not a notes packet |
| 7. LLM parameter-tuning study | Not in scope | Settings expose temperature and max tokens ([#220](https://github.com/mahmoudazaid/Kernector/issues/220)). There is no experiment dataset or tuning presentation |

---

## What the brief’s talk must show

[`AE.CAP_afa.md`](../AE.CAP_afa.md) asks for six points in 10 minutes + 5 minutes of questions. Mapping to the outline:

| Brief point | Outline | Ready? |
|---|---|---|
| 1. The problem | [`presentation.md`](capstone/presentation.md) slides 2–3 | Ready to say |
| 2. Your solution | Slides 4–6; architecture image | Ready to show in the UI |
| 3. The data | Case study §5; live Issue text, not a stale index | Ready to say |
| 4. Evaluation | Slide 7 | Left: coverage numbers from [#341](https://github.com/mahmoudazaid/Kernector/issues/341) and user-study findings from [#343](https://github.com/mahmoudazaid/Kernector/issues/343). Until then, show the plan and claim no scores |
| 5. Challenges | Slide 8 (domain-agnostic pack vs ticket types in core) | Ready to say |
| 6. What’s next | Slide 8 | Ready to say |

---

## Gaps before a review booking

1. **Ethics.** Add a short section (case study or README) that states privacy controls already built and how bias is handled (human selection before cases are written, evidence-only generation, refusal when the Issue lacks evidence). The brief scores demonstrated awareness, including bias.
2. **Evaluation.** Land [#341](https://github.com/mahmoudazaid/Kernector/issues/341) and fill case study §6. Until then, the talk should state that no coverage-quality numbers are claimed.
3. **User testing.** Land [#343](https://github.com/mahmoudazaid/Kernector/issues/343) (five QA users) and fill case study §7. Case 2 step 5 asks for user testing.
4. **Demo evidence.** Run [`demo.md`](capstone/demo.md) Path A and fill the verification note (date, commit, Issue, draft id).
5. **Presentation.** Deliver the 10 + 5 talk and record the link in the [evidence tracker](capstone/README.md#evidence-tracker). Name SCR on the case-study structure, or add a SMART line for the capstone outcome.

---

## Demo checklist (capstone review)

1. State the problem and users in one minute — case study §1 ([#342](https://github.com/mahmoudazaid/Kernector/issues/342)).
2. Show architecture: core, Software Delivery pack, composition, Next.js + MCP.
3. Path A: `/chat` with one Issue URL → **Start Test Design** → drop/add a candidate → manual vs Cucumber → generated cases → edit shows **Saved** ([`demo.md`](capstone/demo.md)).
4. Show fail-closed behavior when the Issue fingerprint changes, or describe it if a live edit is too slow.
5. Show cited RAG chat as the learning-application baseline (Chroma + grounded ask), and say Test Design reads the live Issue rather than the index.
6. Walk privacy: tokens stay on the server; evidence is untrusted; logs are metadata only.
7. Evaluation: show the [#341](https://github.com/mahmoudazaid/Kernector/issues/341) report if it has landed; otherwise show the plan and the existing RAG judge harness, and do not invent coverage scores.
8. Showcase page, linked from the top of `README.md`: [Kernector: reviewed test cases from user story](https://showcase.turingcollege.com/project/4c183de0-867c-470c-9bd2-ded181fc15a7).
