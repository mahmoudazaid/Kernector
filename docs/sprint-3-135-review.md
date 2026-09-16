# Sprint 3 (135.md) — Requirements Review

**Project:** Kernector  
**Spec:** [`135.md`](../135.md)  
**Prior sprint:** [`sprint-2-125-review.md`](sprint-2-125-review.md)  
**Review date:** 2026-09-16 (updated from 2026-09-11)  
**Ticket filter:** GitHub label `Sprint#3` (44 issues: 16 open / 28 closed) plus carryover tickets cited below  
**Verdict:** **LangGraph agent loop, short-term memory, and HITL tool approval are live on `main` (opt-in).** Streamlit is retired (ADR 0004, [#228](https://github.com/mahmoudazaid/Kernector/issues/228)). Grounded RAG chat + Software Delivery Drive-export tool run on FastAPI + Next.js. Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211) remains open for purpose brief / docs and follow-ons: **[#43](https://github.com/mahmoudazaid/Kernector/issues/43)** loop, **[#213](https://github.com/mahmoudazaid/Kernector/issues/213)** short-term memory, and **[#214](https://github.com/mahmoudazaid/Kernector/issues/214)** HITL are **closed**. Long-term cross-thread memory deferred to [#299](https://github.com/mahmoudazaid/Kernector/issues/299). **Max bonus (≥2 medium + 1 hard) is met** for Sprint 3 agent scope (e.g. short-term memory + Drive export tool + external KB connectors).

---

## Summary

| Area | Count |
|------|-------|
| Mandatory Done | 3 / 5 |
| Mandatory Partial | 2 / 5 |
| Optional Done | 7 |
| Optional Partial | 4 |
| Optional Not done | 7 |
| Max bonus (≥2 medium + 1 hard) | **Met** |
| Sprint#3 tickets | 44 (16 open / 28 closed) |
| Primary agent epic | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) (open) |
| Agent loop | [#43](https://github.com/mahmoudazaid/Kernector/issues/43) (**closed**) |
| Short-term memory | [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (**closed**) |
| HITL | [#214](https://github.com/mahmoudazaid/Kernector/issues/214) (**closed**) |

**Agent framing:** Kernector is a **grounded RAG chatbot** with an **opt-in LangGraph ReAct loop** for Software Delivery tool turns. With `SOFTWARE_DELIVERY_AGENT_LOOP=true`, pack orchestrate swaps to `LangGraphToolAgent` (`infrastructure/agents/langgraph_tool_agent.py` behind `ToolCallingAgent`; wired via `composition/software_delivery_agent.py`). Chat intent matches **Google Drive export** only (#309; scaffolding risk/generate/markdown-export retired in #285). Short-term thread memory uses process-scoped `InMemorySaver` (`composition/short_term_memory.py`) keyed `{workspace_id}:{conversation_id}`. HITL pauses allowlisted tools (Drive export) via LangGraph `interrupt()`; Next.js shows `ToolApprovalCard` for approve/reject. Test Design coverage planning (#293) is pack-local (not an agent `Tool`). Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211) stays open for [#212](https://github.com/mahmoudazaid/Kernector/issues/212) / [#215](https://github.com/mahmoudazaid/Kernector/issues/215) and bonus follow-ons.

**Domain purpose (carryover):** Software Delivery Intelligence — grounded chat over delivery knowledge, interactive test-design workflow, Drive export with HITL — target users: QA / engineering teams. Formal Sprint 3 brief still open: [#212](https://github.com/mahmoudazaid/Kernector/issues/212).

**Entry (current):**

```bash
HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload
# Opt-in agent orchestrate + Drive-export intent + short-term memory + HITL:
# SOFTWARE_DELIVERY_AGENT_LOOP=true DOMAIN_TOOL_PACKS=software-delivery ...
cd web && npm ci && npm run dev   # http://localhost:3000
```

Chat / Settings / Documents: `web/app/chat`, `web/app/settings`, `web/app/documents`. Conversations: `web/app/chat/[conversationId]`.

---

## What changed since 2026-09-11

| Change | Evidence |
|--------|----------|
| **[#214](https://github.com/mahmoudazaid/Kernector/issues/214) closed** — HITL tool approval | PR [#311](https://github.com/mahmoudazaid/Kernector/pull/311); `interrupt()` + `ToolApprovalCard` + chat approval HTTP |
| **[#213](https://github.com/mahmoudazaid/Kernector/issues/213) closed** — LangGraph short-term memory | PR [#303](https://github.com/mahmoudazaid/Kernector/pull/303); `InMemorySaver` / `composition/short_term_memory.py`; LT → [#299](https://github.com/mahmoudazaid/Kernector/issues/299) |
| **[#197](https://github.com/mahmoudazaid/Kernector/issues/197) closed** — Drive export tool | PR [#308](https://github.com/mahmoudazaid/Kernector/pull/308); `packs/software_delivery/tools/export_test_cases_google_drive.py` |
| **[#309](https://github.com/mahmoudazaid/Kernector/issues/309) closed** — restore Drive-export agent intent | Intent matcher gated on agent-loop flag; prepared-call path |
| **[#245](https://github.com/mahmoudazaid/Kernector/issues/245) / [#243](https://github.com/mahmoudazaid/Kernector/issues/243) / [#246](https://github.com/mahmoudazaid/Kernector/issues/246) closed** | Chat UX polish, inline document viewer/download, conversation history |
| **[#293](https://github.com/mahmoudazaid/Kernector/issues/293) closed** — interactive test coverage planning | Pack-local Test Design workflow (not an agent Tool) |
| **[#286](https://github.com/mahmoudazaid/Kernector/issues/286) closed** — GitHub repo + Project Issues sync | Hard #5 connector progress |
| **[#57](https://github.com/mahmoudazaid/Kernector/issues/57) closed** — actionable provider errors | Safer HTTP error surfacing |
| Architecture docs updated for agent / memory / HITL | PR [#306](https://github.com/mahmoudazaid/Kernector/pull/306); `ARCHITECTURE.md` |

---

## Mandatory requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agent purpose (clear purpose, usefulness, target users) | Purpose | Partial | README / `packs/software_delivery/README.md`; dedicated Sprint 3 brief missing | [#212](https://github.com/mahmoudazaid/Kernector/issues/212) (open, `mandatory`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Core functionality (primary tasks + user interactions) | Agent | Done | RAG ask + opt-in LangGraph orchestrate ([#43](https://github.com/mahmoudazaid/Kernector/issues/43)); Drive export tool ([#197](https://github.com/mahmoudazaid/Kernector/issues/197)); HITL approve/reject ([#214](https://github.com/mahmoudazaid/Kernector/issues/214)); thread memory ([#213](https://github.com/mahmoudazaid/Kernector/issues/213)); Test Design workflow ([#293](https://github.com/mahmoudazaid/Kernector/issues/293)) | [#43](https://github.com/mahmoudazaid/Kernector/issues/43) / [#197](https://github.com/mahmoudazaid/Kernector/issues/197) / [#214](https://github.com/mahmoudazaid/Kernector/issues/214) / [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (**closed**) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| User interface (friendly UI for all functionalities) | UI | Done | Next.js chat/settings/documents; history [#246](https://github.com/mahmoudazaid/Kernector/issues/246); polish [#245](https://github.com/mahmoudazaid/Kernector/issues/245); viewer [#243](https://github.com/mahmoudazaid/Kernector/issues/243); HITL card; chunk inspect [#210](https://github.com/mahmoudazaid/Kernector/issues/210). Optional further UX split [#36](https://github.com/mahmoudazaid/Kernector/issues/36) still open | [#126](https://github.com/mahmoudazaid/Kernector/issues/126)/[#235](https://github.com/mahmoudazaid/Kernector/issues/235)–[#237](https://github.com/mahmoudazaid/Kernector/issues/237)/[#228](https://github.com/mahmoudazaid/Kernector/issues/228)/[#210](https://github.com/mahmoudazaid/Kernector/issues/210)/[#243](https://github.com/mahmoudazaid/Kernector/issues/243)/[#245](https://github.com/mahmoudazaid/Kernector/issues/245)/[#246](https://github.com/mahmoudazaid/Kernector/issues/246)/[#214](https://github.com/mahmoudazaid/Kernector/issues/214) (closed) | [#124](https://github.com/mahmoudazaid/Kernector/issues/124) |
| Technical implementation (tools/libs, errors, real-world use) | Technical | Done | LangChain + LangGraph adapter, OpenRouter/Ollama, `domain/errors.py`, `input_safety.py`, HITL interrupts, short-term checkpointer; LT memory deferred [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | Sprint 2 carryover #89, #98, #96, #97 (closed); [#43](https://github.com/mahmoudazaid/Kernector/issues/43)/[#213](https://github.com/mahmoudazaid/Kernector/issues/213)/[#214](https://github.com/mahmoudazaid/Kernector/issues/214)/[#57](https://github.com/mahmoudazaid/Kernector/issues/57) (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Documentation (usage, examples, technical decisions) | Docs | Partial | `README.md`, `ARCHITECTURE.md` (agent / memory / HITL), ADRs; review-facing Sprint 3 how-to / purpose brief incomplete | [#215](https://github.com/mahmoudazaid/Kernector/issues/215) (open, `mandatory`); [#212](https://github.com/mahmoudazaid/Kernector/issues/212) (open); Sprint 2 #104, #105 | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#75](https://github.com/mahmoudazaid/Kernector/issues/75) |

**Gap vs 135.md topics:** LangGraph **agent loop — Done (opt-in)**. **Short-term graph memory — Done** (process-local; long-term → #299). **Human-in-the-loop — Done** for Drive export. Remaining mandatory gaps: purpose brief + review-facing agent docs.

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
| Long-term or short-term memory (LangChain/LangGraph) | Medium | Done | Short-term `InMemorySaver` per conversation when agent loop on; LT across threads open as [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (**closed**, `bonus`); related [#246](https://github.com/mahmoudazaid/Kernector/issues/246) (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| One more function tool calling an external API | Medium | Done | Google Drive **export** tool + Drive sync connector | [#197](https://github.com/mahmoudazaid/Kernector/issues/197)/[#196](https://github.com/mahmoudazaid/Kernector/issues/196)/[#254](https://github.com/mahmoudazaid/Kernector/issues/254) (closed); #198, #199 (open, `bonus`) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Auth + personalisation | Medium | Not done | Drive OAuth only; no end-user auth | [#182](https://github.com/mahmoudazaid/Kernector/issues/182) (open, `bonus`) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Feedback loop (rate responses → improve agent) | Medium | Not done | — | [#219](https://github.com/mahmoudazaid/Kernector/issues/219) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| 2 extra tools (5 total) + enable/disable UI + plugin system | Medium | Partial | 1 registered SD tool (Drive export); Test Design is pack-local; pack enable via `DOMAIN_TOOL_PACKS`; no per-tool toggle / dynamic plugin UI | [#221](https://github.com/mahmoudazaid/Kernector/issues/221) (open); extras #198–#199 (open) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Multi-model support (OpenAI, Anthropic, …) | Medium | Done | OpenRouter multi-model + Ollama in Settings | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed); [#41](https://github.com/mahmoudazaid/Kernector/issues/41) still open (broader native providers) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| ≥1 security guard; separate developer settings from UX | Medium | Done | `input_safety.py`, grounded RAG policy; `/settings` vs `/chat` | [#97](https://github.com/mahmoudazaid/Kernector/issues/97) (closed); [#36](https://github.com/mahmoudazaid/Kernector/issues/36) (open — further UX split) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |

### Hard

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agentic RAG (RAG inside LangChain/LangGraph agent) | Hard | Partial | Advanced RAG Done (rewrite/retrieve, hybrid); agent tool turns still retrieve on #170 path — retrieve is not a graph node | [#216](https://github.com/mahmoudazaid/Kernector/issues/216) (open, `bonus`); Sprint 2 #87, #185 (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| LLM observability (LangSmith, Langfuse, …) | Hard | Not done | Structured JSON logging only (`application/observability.py`); no LangSmith/Langfuse | [#222](https://github.com/mahmoudazaid/Kernector/issues/222) (open, `bonus`); [#160](https://github.com/mahmoudazaid/Kernector/issues/160) (closed) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| AI evaluation report (Ragas / DeepEval) | Hard | Partial | Custom offline + LLM-as-Judge harness Done (`composition/evaluate.py`, `data/eval/`); not Ragas/DeepEval; live HTTP/Next.js trigger open | [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) (closed, `bonus`); [#263](https://github.com/mahmoudazaid/Kernector/issues/263), [#264](https://github.com/mahmoudazaid/Kernector/issues/264) (open, `bonus`) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Learn from user feedback (adapt capabilities) | Hard | Not done | Depends on [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | [#223](https://github.com/mahmoudazaid/Kernector/issues/223) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Integrate external data sources (APIs / websites) | Hard | Done | Google Drive sync + UI; GitHub repo + Project Issues sync | [#196](https://github.com/mahmoudazaid/Kernector/issues/196), [#254](https://github.com/mahmoudazaid/Kernector/issues/254), [#286](https://github.com/mahmoudazaid/Kernector/issues/286) (closed); [#195](https://github.com/mahmoudazaid/Kernector/issues/195) OneDrive (open) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |

---

## Epic index (Sprint 3 + carryover)

| Epic / issue | Title | State | Sprint 3 relevance |
|---|---|---|---|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | **Epic: LangGraph agent, memory, and HITL** | Open | Primary Sprint 3 epic — loop/memory/HITL Done; purpose/docs + bonus open |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain agent loop for multi-step tool orchestration | **Closed** | Opt-in LangGraph orchestrate shipped |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | LangGraph short-term memory | **Closed** | Process-local checkpointer; LT → #299 |
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | HITL interrupts for tool approval | **Closed** | Drive export allowlist + Next.js card |
| [#124](https://github.com/mahmoudazaid/Kernector/issues/124) | EPIC: Next.js presentation foundation | Open | UI mandatory path largely closed; epic may still track polish |
| [#9](https://github.com/mahmoudazaid/Kernector/issues/9) | Software Delivery Intelligence domain pack | Open | Agent domain / tools / plugins |
| [#149](https://github.com/mahmoudazaid/Kernector/issues/149) | Epic: Prompt and Command Management | Open | Personality / custom commands |
| [#148](https://github.com/mahmoudazaid/Kernector/issues/148) | Model Runtime and Provider Experience | — | LLM list / tokens / settings |
| [#68](https://github.com/mahmoudazaid/Kernector/issues/68) | Generic Knowledge Foundation | — | External sources / Drive / GitHub |
| [#70](https://github.com/mahmoudazaid/Kernector/issues/70) | RAG Orchestration | — | Grounded retrieve path |
| [#72](https://github.com/mahmoudazaid/Kernector/issues/72) | Security | — | Guards + auth optional |
| [#74](https://github.com/mahmoudazaid/Kernector/issues/74) | Quality / Evaluation | — | Judge eval / Langfuse hard options |
| [#75](https://github.com/mahmoudazaid/Kernector/issues/75) | Documentation | — | Ops / architecture docs |

### Agent gap tickets (#211 children / linked)

| # | Title | Maps to | State |
|---|-------|---------|-------|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | Epic: LangGraph agent, memory, and HITL | Sprint 3 foundation | Open |
| [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | Write Sprint 3 agent purpose brief | Mandatory #1 | Open |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain / LangGraph agent loop | Mandatory #2 | **Closed** |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | LangGraph short-term memory | Medium #2 | **Closed** |
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | HITL interrupts for tool approval | Mandatory #4 / HITL | **Closed** |
| [#215](https://github.com/mahmoudazaid/Kernector/issues/215) | Document Sprint 3 agent usage | Mandatory #5 | Open |
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216) | Agentic RAG in LangGraph | Hard #1 | Open |
| [#217](https://github.com/mahmoudazaid/Kernector/issues/217) | ChatGPT critique | Easy #1 | Open |
| [#218](https://github.com/mahmoudazaid/Kernector/issues/218) | Agent personality | Easy #2 | Open |
| [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | Response rating feedback loop | Medium #5 | Open |
| [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | Generation settings UI | Easy #4 | Open (UI Done) |
| [#221](https://github.com/mahmoudazaid/Kernector/issues/221) | Tool enable/disable + plugins | Medium #6 | Open |
| [#222](https://github.com/mahmoudazaid/Kernector/issues/222) | LangSmith or Langfuse | Hard #2 | Open |
| [#223](https://github.com/mahmoudazaid/Kernector/issues/223) | Adapt capabilities from feedback | Hard #4 | Open |
| [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | Consent-aware long-term memory across threads | Medium #2 follow-on | Open |

### Presentation / connector / agent progress (closed since prior reviews)

| # | Title | Notes |
|---|-------|-------|
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | HITL tool approval | Closed 2026-09-16 — Mandatory #4 |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | Short-term memory | Closed 2026-09-15 — Medium #2 |
| [#197](https://github.com/mahmoudazaid/Kernector/issues/197) | Drive export tool | Closed 2026-09-15 — Medium #3 |
| [#309](https://github.com/mahmoudazaid/Kernector/issues/309) | Drive export agent prepared call | Closed 2026-09-16 |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangGraph agent loop | Closed — Mandatory #2 |
| [#245](https://github.com/mahmoudazaid/Kernector/issues/245), [#243](https://github.com/mahmoudazaid/Kernector/issues/243), [#246](https://github.com/mahmoudazaid/Kernector/issues/246) | Chat UX / viewer / history | Closed — UI mandatory |
| [#286](https://github.com/mahmoudazaid/Kernector/issues/286) | GitHub connector | Closed — Hard #5 |
| [#293](https://github.com/mahmoudazaid/Kernector/issues/293) | Test coverage planning | Closed — pack-local workflow |
| [#210](https://github.com/mahmoudazaid/Kernector/issues/210) | Inspect stored chunks | Closed — Documents UI |
| [#228](https://github.com/mahmoudazaid/Kernector/issues/228) | Retire Streamlit | ADR 0004 |
| [#235](https://github.com/mahmoudazaid/Kernector/issues/235)–[#237](https://github.com/mahmoudazaid/Kernector/issues/237) | Chat / documents / settings Next.js parity | Closed |
| [#196](https://github.com/mahmoudazaid/Kernector/issues/196), [#254](https://github.com/mahmoudazaid/Kernector/issues/254) | Google Drive sync + UI | Closed — Hard #5 / Medium #3 |
| [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) | Offline eval harness + LLM-as-Judge | Closed — Hard #3 Partial (custom, not Ragas) |

### Still open (Sprint#3-labelled)

| # | Title | Notes |
|---|-------|-------|
| [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | Agent purpose brief | Mandatory #1 |
| [#215](https://github.com/mahmoudazaid/Kernector/issues/215) | Agent usage docs | Mandatory #5 |
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216)–[#223](https://github.com/mahmoudazaid/Kernector/issues/223) | Bonus agent follow-ons | Easy/Medium/Hard open set |
| [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | Generation settings AC | UI Done; ticket open |
| [#198](https://github.com/mahmoudazaid/Kernector/issues/198) | OneDrive export tool | Bonus |
| [#263](https://github.com/mahmoudazaid/Kernector/issues/263), [#264](https://github.com/mahmoudazaid/Kernector/issues/264) | Live Judge eval HTTP / settings | Bonus |
| [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | Long-term memory | Follow-on from #213 |
| [#36](https://github.com/mahmoudazaid/Kernector/issues/36) | Further UX / ops split | Bonus polish |
| [#298](https://github.com/mahmoudazaid/Kernector/issues/298) | Reuse BDD step defs in test design | Domain enhancement |

---

## Evaluation criteria checklist ([135.md](../135.md))

| Criterion | Ready for review? | Notes |
|-----------|-------------------|--------|
| Problem definition | Partial | SD domain clear; brief [#212](https://github.com/mahmoudazaid/Kernector/issues/212) open |
| Understanding core concepts | Partial → near ready | Agent loop / memory / HITL in code + `ARCHITECTURE.md`; still need review-facing docs [#215](https://github.com/mahmoudazaid/Kernector/issues/215) |
| Technical implementation | Ready | Next.js UI + KB + security + LangGraph + short-term memory + HITL on `main` |
| Reflection and improvement | Not ready | [#215](https://github.com/mahmoudazaid/Kernector/issues/215) + critique [#217](https://github.com/mahmoudazaid/Kernector/issues/217) |
| Bonus (≥2 medium + 1 hard) | **Met** | Medium: short-term memory [#213](https://github.com/mahmoudazaid/Kernector/issues/213) + Drive export API tool [#197](https://github.com/mahmoudazaid/Kernector/issues/197) (also multi-model + security). Hard: external sources Drive + GitHub ([#196](https://github.com/mahmoudazaid/Kernector/issues/196)/[#254](https://github.com/mahmoudazaid/Kernector/issues/254)/[#286](https://github.com/mahmoudazaid/Kernector/issues/286)) |

---

## Suggested Sprint 3 path (remaining)

1. [#212](https://github.com/mahmoudazaid/Kernector/issues/212) — write **agent purpose** brief.
2. ~~[#43](https://github.com/mahmoudazaid/Kernector/issues/43) — LangGraph/LangChain **agent loop**~~ **Done**.
3. ~~[#213](https://github.com/mahmoudazaid/Kernector/issues/213) — short-term **memory**~~ **Done** (optional LT: [#299](https://github.com/mahmoudazaid/Kernector/issues/299)).
4. ~~[#214](https://github.com/mahmoudazaid/Kernector/issues/214) — **HITL**~~ **Done**.
5. [#215](https://github.com/mahmoudazaid/Kernector/issues/215) — agent **docs** for review (flag, demo steps, architecture).
6. ~~UI polish [#245](https://github.com/mahmoudazaid/Kernector/issues/245) / [#243](https://github.com/mahmoudazaid/Kernector/issues/243) / [#246](https://github.com/mahmoudazaid/Kernector/issues/246)~~ **Done**.
7. Demo on **Next.js** (`web/` + FastAPI); Streamlit is retired.
8. Close [#220](https://github.com/mahmoudazaid/Kernector/issues/220) if Settings AC is satisfied.
9. Optional further bonus: agentic RAG [#216](https://github.com/mahmoudazaid/Kernector/issues/216), observability [#222](https://github.com/mahmoudazaid/Kernector/issues/222), more tools [#198](https://github.com/mahmoudazaid/Kernector/issues/198)/[#221](https://github.com/mahmoudazaid/Kernector/issues/221).

---

## Demo checklist (target for Sprint 3 review)

1. State agent purpose and users in one minute ([#212](https://github.com/mahmoudazaid/Kernector/issues/212) — still write this).
2. Show agent graph (or architecture diagram): nodes, state, tools ([#43](https://github.com/mahmoudazaid/Kernector/issues/43) — via `SOFTWARE_DELIVERY_AGENT_LOOP=true`).
3. Run a Drive-export tool turn on the agent path (intent + prepared call + HITL).
4. Show short-term memory: follow-up in the same conversation_id uses checkpoint ([#213](https://github.com/mahmoudazaid/Kernector/issues/213)).
5. HITL: pause before Drive export; approve/reject in Next.js ([#214](https://github.com/mahmoudazaid/Kernector/issues/214)).
6. Optional: agentic RAG retrieve inside the graph ([#216](https://github.com/mahmoudazaid/Kernector/issues/216)).
7. Optional: tokens/cost, model picker, observability ([#40](https://github.com/mahmoudazaid/Kernector/issues/40)/[#220](https://github.com/mahmoudazaid/Kernector/issues/220), [#222](https://github.com/mahmoudazaid/Kernector/issues/222)).
8. Show Next.js chat + history + Settings + Documents (chunk inspect [#210](https://github.com/mahmoudazaid/Kernector/issues/210); viewer [#243](https://github.com/mahmoudazaid/Kernector/issues/243); Drive/GitHub sync for Hard #5).

Until purpose brief + review docs land, use `ARCHITECTURE.md` for agent/memory/HITL detail and [`sprint-2-project-review-guide.md`](sprint-2-project-review-guide.md) for the Sprint 2 RAG baseline (run against Next.js, not Streamlit).
