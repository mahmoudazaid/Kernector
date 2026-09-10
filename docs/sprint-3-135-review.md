# Sprint 3 (135.md) — Requirements Review

**Project:** Kernector  
**Spec:** [`135.md`](../135.md)  
**Prior sprint:** [`sprint-2-125-review.md`](sprint-2-125-review.md)  
**Review date:** 2026-09-10  
**Ticket filter:** GitHub label `Sprint#3` (61 issues: 39 open / 22 closed) plus carryover tickets cited below  
**Verdict:** **Next.js presentation is live; agent stack is not.** Streamlit is retired (ADR 0004, [#228](https://github.com/mahmoudazaid/Kernector/issues/228)). Grounded RAG chat + intent-routed Software Delivery tools run on FastAPI + Next.js. Sprint 3 **LangGraph agent loop**, **graph memory**, and **HITL** remain open under Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211). Max bonus (≥2 medium + 1 hard **for Sprint 3 agent scope**) not met yet.

---

## Summary

| Area | Count |
|------|-------|
| Mandatory Done | 0 / 5 |
| Mandatory Partial | 5 / 5 |
| Optional Done | 4 |
| Optional Partial | 6 |
| Optional Not done | 8 |
| Max bonus (≥2 medium + 1 hard) | Not met yet |
| Sprint#3 tickets | 61 (39 open / 22 closed) |
| Primary agent epic | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) (open) |

**Agent framing:** Kernector is still a **grounded RAG chatbot** with **intent-routed domain tools** (`packs/software_delivery/chat_intent.py` → `composition/tool_augmented_ask.py`). There is **no** LangGraph/`StateGraph` agent loop, checkpointer, or tool-approval interrupt in code. Sprint 3 delivery is tracked by Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211) and agent loop [#43](https://github.com/mahmoudazaid/Kernector/issues/43) (both open, `mandatory`).

**Domain purpose (carryover):** Software Delivery Intelligence — risk scoring, grounded test-case generation/export, RAG over delivery knowledge — target users: QA / engineering teams. Formal Sprint 3 brief still open: [#212](https://github.com/mahmoudazaid/Kernector/issues/212).

**Entry (current):**

```bash
HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload
cd web && npm ci && npm run dev   # http://localhost:3000
```

Chat / Settings / Documents: `web/app/chat`, `web/app/settings`, `web/app/documents`.

---

## Mandatory requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agent purpose (clear purpose, usefulness, target users) | Purpose | Partial | README / `packs/software_delivery/README.md`; dedicated Sprint 3 brief missing | [#212](https://github.com/mahmoudazaid/Kernector/issues/212) (open, `mandatory`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Core functionality (primary tasks + user interactions) | Agent | Partial | RAG ask + SD tools via `composition/tool_augmented_ask.py`, `packs/software_delivery/orchestration.py` — **no** LangGraph agent loop | [#43](https://github.com/mahmoudazaid/Kernector/issues/43) (open, `mandatory`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| User interface (friendly UI for all functionalities) | UI | Partial | Next.js chat/settings/documents Done; Streamlit retired. Open: HITL UI, chat history list, polish | [#126](https://github.com/mahmoudazaid/Kernector/issues/126) (closed); [#235](https://github.com/mahmoudazaid/Kernector/issues/235)/[#236](https://github.com/mahmoudazaid/Kernector/issues/236)/[#237](https://github.com/mahmoudazaid/Kernector/issues/237)/[#228](https://github.com/mahmoudazaid/Kernector/issues/228) (closed); epic [#124](https://github.com/mahmoudazaid/Kernector/issues/124) (open); [#214](https://github.com/mahmoudazaid/Kernector/issues/214), [#246](https://github.com/mahmoudazaid/Kernector/issues/246) (open) | [#124](https://github.com/mahmoudazaid/Kernector/issues/124) |
| Technical implementation (tools/libs, errors, real-world use) | Technical | Partial | LangChain + OpenRouter/Ollama, `domain/errors.py`, `input_safety.py`, HTTP errors; missing LangGraph state/memory/HITL | Sprint 2 carryover #89, #98, #96, #97 (closed); [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (open, bonus), [#214](https://github.com/mahmoudazaid/Kernector/issues/214) (open, `mandatory`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Documentation (usage, examples, technical decisions) | Docs | Partial | `README.md`, `ARCHITECTURE.md`, ADRs, pack README; agent how-to incomplete | [#215](https://github.com/mahmoudazaid/Kernector/issues/215) (open, `mandatory`); Sprint 2 #104, #105 | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#75](https://github.com/mahmoudazaid/Kernector/issues/75) |

**Gap vs 135.md topics:** LangGraph/LangChain agents, long-term/short-term **graph** memory, human-in-the-loop — **not implemented**. Tool calling remains intent-routed, not native agent function calling inside a graph.

---

## Optional requirements

### Easy

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| ChatGPT critique (usability / security / prompts) | Easy | Not done | — | [#217](https://github.com/mahmoudazaid/Kernector/issues/217) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Agent personality (formal / friendly / concise) | Easy | Not done | — | [#218](https://github.com/mahmoudazaid/Kernector/issues/218) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#149](https://github.com/mahmoudazaid/Kernector/issues/149) |
| Choose from a list of LLMs | Easy | Done | OpenRouter model list + Ollama in Next.js Settings | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed); Settings UI via [#237](https://github.com/mahmoudazaid/Kernector/issues/237) (closed) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| OpenAI settings as sliders/fields (temperature, max tokens, …) | Easy | Done | `domain/model_settings.py` → settings API → `web/components/settings/SettingsPanel.tsx` | [#220](https://github.com/mahmoudazaid/Kernector/issues/220) (open — AC close pending; UI shipped) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Interactive help / chatbot guide | Easy | Not done | Field-level help only | [#180](https://github.com/mahmoudazaid/Kernector/issues/180) (open, `bonus`) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) / [#124](https://github.com/mahmoudazaid/Kernector/issues/124) |

### Medium

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Token usage and costs | Medium | Partial | Tokens in chat run details; `Usage.cost` not exposed in HTTP/`run_meta` UI | #40, #49, #50 (open, `bonus`) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Long-term or short-term memory (LangChain/LangGraph) | Medium | Not done | Client session + `AskRequest.history` only; no graph memory / store | [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (open, `bonus`); related [#246](https://github.com/mahmoudazaid/Kernector/issues/246) (open) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| One more function tool calling an external API | Medium | Partial | Google Drive **connector** shipped; Drive/OneDrive/Xray **chat export tools** still open | [#196](https://github.com/mahmoudazaid/Kernector/issues/196)/[#254](https://github.com/mahmoudazaid/Kernector/issues/254) (closed); #197, #198, #199 (open, `bonus`) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Auth + personalisation | Medium | Not done | Drive OAuth only; no end-user auth | [#182](https://github.com/mahmoudazaid/Kernector/issues/182) (open, `bonus`) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Feedback loop (rate responses → improve agent) | Medium | Not done | — | [#219](https://github.com/mahmoudazaid/Kernector/issues/219) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| 2 extra tools (5 total) + enable/disable UI + plugin system | Medium | Partial | 3 SD tools Done; pack enable via `DOMAIN_TOOL_PACKS`; no per-tool toggle / dynamic plugin UI | [#221](https://github.com/mahmoudazaid/Kernector/issues/221) (open); extras #197–#199 (open) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Multi-model support (OpenAI, Anthropic, …) | Medium | Done | OpenRouter multi-model + Ollama in Settings | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed); [#41](https://github.com/mahmoudazaid/Kernector/issues/41) still open (broader native providers) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| ≥1 security guard; separate developer settings from UX | Medium | Done | `input_safety.py`, grounded RAG policy; `/settings` vs `/chat` | [#97](https://github.com/mahmoudazaid/Kernector/issues/97) (closed); [#36](https://github.com/mahmoudazaid/Kernector/issues/36) (open — further UX split) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |

### Hard

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agentic RAG (RAG inside LangChain/LangGraph agent) | Hard | Partial | Advanced RAG Done (rewrite/retrieve, hybrid); **not** agentic graph RAG | [#216](https://github.com/mahmoudazaid/Kernector/issues/216) (open, `bonus`); Sprint 2 #87, #185 (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| LLM observability (LangSmith, Langfuse, …) | Hard | Not done | Structured JSON logging only (`application/observability.py`); no LangSmith/Langfuse | [#222](https://github.com/mahmoudazaid/Kernector/issues/222) (open, `bonus`); [#160](https://github.com/mahmoudazaid/Kernector/issues/160) (closed) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| AI evaluation report (Ragas / DeepEval) | Hard | Partial | Custom offline + LLM-as-Judge harness Done (`composition/evaluate.py`, `data/eval/`); not Ragas/DeepEval; live HTTP/Next.js trigger open | [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) (closed, `bonus`); [#263](https://github.com/mahmoudazaid/Kernector/issues/263), [#264](https://github.com/mahmoudazaid/Kernector/issues/264) (open, `bonus`) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Learn from user feedback (adapt capabilities) | Hard | Not done | Depends on [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | [#223](https://github.com/mahmoudazaid/Kernector/issues/223) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Integrate external data sources (APIs / websites) | Hard | Partial | Google Drive sync + Next.js panel shipped; OneDrive open | [#196](https://github.com/mahmoudazaid/Kernector/issues/196), [#254](https://github.com/mahmoudazaid/Kernector/issues/254) (closed); [#195](https://github.com/mahmoudazaid/Kernector/issues/195) (open) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |

---

## Epic index (Sprint 3 + carryover)

| Epic / issue | Title | State | Sprint 3 relevance |
|---|---|---|---|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | **Epic: LangGraph agent, memory, and HITL** | Open | Primary Sprint 3 epic |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain agent loop for multi-step tool orchestration | Open | Core agent delivery |
| [#124](https://github.com/mahmoudazaid/Kernector/issues/124) | EPIC: Next.js presentation foundation | Open | UI mandatory path (migration largely closed under it) |
| [#9](https://github.com/mahmoudazaid/Kernector/issues/9) | Software Delivery Intelligence domain pack | Open | Agent domain / tools / plugins |
| [#149](https://github.com/mahmoudazaid/Kernector/issues/149) | Epic: Prompt and Command Management | Open | Personality / custom commands |
| [#148](https://github.com/mahmoudazaid/Kernector/issues/148) | Model Runtime and Provider Experience | — | LLM list / tokens / settings |
| [#68](https://github.com/mahmoudazaid/Kernector/issues/68) | Generic Knowledge Foundation | — | External sources / Drive |
| [#70](https://github.com/mahmoudazaid/Kernector/issues/70) | RAG Orchestration | — | Grounded retrieve path |
| [#72](https://github.com/mahmoudazaid/Kernector/issues/72) | Security | — | Guards + auth optional |
| [#74](https://github.com/mahmoudazaid/Kernector/issues/74) | Quality / Evaluation | — | Judge eval / Langfuse hard options |
| [#75](https://github.com/mahmoudazaid/Kernector/issues/75) | Documentation | — | Ops / architecture docs |

### Agent gap tickets (#211 children / linked)

| # | Title | Maps to | State |
|---|-------|---------|-------|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | Epic: LangGraph agent, memory, and HITL | Sprint 3 foundation | Open |
| [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | Write Sprint 3 agent purpose brief | Mandatory #1 | Open |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain / LangGraph agent loop | Mandatory #2 | Open |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | LangGraph short-term and long-term memory | Medium #2 | Open |
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | HITL interrupts for tool approval | Mandatory #4 / HITL | Open |
| [#215](https://github.com/mahmoudazaid/Kernector/issues/215) | Document Sprint 3 agent usage | Mandatory #5 | Open |
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216) | Agentic RAG in LangGraph | Hard #1 | Open |
| [#217](https://github.com/mahmoudazaid/Kernector/issues/217) | ChatGPT critique | Easy #1 | Open |
| [#218](https://github.com/mahmoudazaid/Kernector/issues/218) | Agent personality | Easy #2 | Open |
| [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | Response rating feedback loop | Medium #5 | Open |
| [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | Generation settings UI | Easy #4 | Open (UI Done) |
| [#221](https://github.com/mahmoudazaid/Kernector/issues/221) | Tool enable/disable + plugins | Medium #6 | Open |
| [#222](https://github.com/mahmoudazaid/Kernector/issues/222) | LangSmith or Langfuse | Hard #2 | Open |
| [#223](https://github.com/mahmoudazaid/Kernector/issues/223) | Adapt capabilities from feedback | Hard #4 | Open |

### Presentation / connector progress (Sprint#3 closed since prior review)

| # | Title | Notes |
|---|-------|-------|
| [#228](https://github.com/mahmoudazaid/Kernector/issues/228) | Retire Streamlit | ADR 0004 |
| [#235](https://github.com/mahmoudazaid/Kernector/issues/235)–[#237](https://github.com/mahmoudazaid/Kernector/issues/237) | Chat / documents / settings Next.js parity | Closed |
| [#196](https://github.com/mahmoudazaid/Kernector/issues/196), [#254](https://github.com/mahmoudazaid/Kernector/issues/254) | Google Drive sync + UI | Closed — Hard #5 / Medium #3 progress |
| [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) | Offline eval harness + LLM-as-Judge | Closed — Hard #3 Partial (custom, not Ragas) |

---

## Evaluation criteria checklist ([135.md](../135.md))

| Criterion | Ready for review? | Notes |
|-----------|-------------------|--------|
| Problem definition | Partial | SD domain clear; brief [#212](https://github.com/mahmoudazaid/Kernector/issues/212) open |
| Understanding core concepts | Not ready | Needs agent docs [#215](https://github.com/mahmoudazaid/Kernector/issues/215) + agent loop [#43](https://github.com/mahmoudazaid/Kernector/issues/43) |
| Technical implementation | Partial | Next.js UI + KB + security exist; agent stack [#211](https://github.com/mahmoudazaid/Kernector/issues/211) open |
| Reflection and improvement | Not ready | [#215](https://github.com/mahmoudazaid/Kernector/issues/215) + critique [#217](https://github.com/mahmoudazaid/Kernector/issues/217) |
| Bonus (≥2 medium + 1 hard) | Not met | Medium Done (carryover): multi-model + security. Need a Sprint 3 hard Done (e.g. [#216](https://github.com/mahmoudazaid/Kernector/issues/216) / [#222](https://github.com/mahmoudazaid/Kernector/issues/222)) plus at least one new medium (e.g. [#213](https://github.com/mahmoudazaid/Kernector/issues/213) or external API tool #197/#199) |

---

## Suggested Sprint 3 path

1. [#212](https://github.com/mahmoudazaid/Kernector/issues/212) — write **agent purpose** brief.
2. [#43](https://github.com/mahmoudazaid/Kernector/issues/43) — LangGraph/LangChain **agent loop** (under Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211)).
3. [#213](https://github.com/mahmoudazaid/Kernector/issues/213) — **memory** (checkpoint / optional long-term store).
4. [#214](https://github.com/mahmoudazaid/Kernector/issues/214) — **HITL** for high-impact tools (wire into Next.js chat).
5. [#215](https://github.com/mahmoudazaid/Kernector/issues/215) — agent **docs** for review.
6. Demo on **Next.js** (`web/` + FastAPI); Streamlit is retired.
7. Close [#220](https://github.com/mahmoudazaid/Kernector/issues/220) if Settings AC is satisfied.
8. Choose **≥2 medium + 1 hard** for max bonus (e.g. #213 + #197/#199 + #216 or #222).

---

## Demo checklist (target for Sprint 3 review)

1. State agent purpose and users in one minute ([#212](https://github.com/mahmoudazaid/Kernector/issues/212)).
2. Show agent graph (or architecture diagram): nodes, state, tools ([#43](https://github.com/mahmoudazaid/Kernector/issues/43)).
3. Run a multi-step task that needs ≥2 tool calls without manual intent keywords if agent-driven.
4. Show memory: follow-up turn uses prior context / checkpoint ([#213](https://github.com/mahmoudazaid/Kernector/issues/213)).
5. Optional HITL: pause before a risky tool; approve/reject in Next.js ([#214](https://github.com/mahmoudazaid/Kernector/issues/214)).
6. Optional: agentic RAG retrieve inside the graph; citations still visible ([#216](https://github.com/mahmoudazaid/Kernector/issues/216)).
7. Optional: tokens/cost, model picker, observability ([#40](https://github.com/mahmoudazaid/Kernector/issues/40)/[#220](https://github.com/mahmoudazaid/Kernector/issues/220), [#222](https://github.com/mahmoudazaid/Kernector/issues/222)).
8. Show Next.js chat + Settings + Documents (and Google Drive sync if demoing Hard #5).

Until the agent path exists, use [`sprint-2-project-review-guide.md`](sprint-2-project-review-guide.md) only for the Sprint 2 RAG/tools baseline (run against Next.js, not Streamlit).
