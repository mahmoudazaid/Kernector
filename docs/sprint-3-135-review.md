# Sprint 3 (135.md) — Requirements Review

**Project:** Kernector  
**Spec:** [`135.md`](../135.md)  
**Prior sprint:** [`sprint-2-125-review.md`](sprint-2-125-review.md)  
**Review date:** 2026-09-22 (updated from 2026-09-16)  
**Ticket filter:** GitHub label `Sprint#3` (41 issues: 9 open / 32 closed) plus carryover tickets cited below  
**Verdict:** **LangGraph agent loop, short-term memory, HITL tool approval, and agentic RAG retrieve are live on `main` (opt-in).** Streamlit is retired (ADR 0004, [#228](https://github.com/mahmoudazaid/Kernector/issues/228)). Grounded RAG chat + Software Delivery Drive-export tool run on FastAPI + Next.js. Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211) remains open for review-facing agent docs ([#215](https://github.com/mahmoudazaid/Kernector/issues/215)) and leftover bonus: **[#43](https://github.com/mahmoudazaid/Kernector/issues/43)** loop, **[#213](https://github.com/mahmoudazaid/Kernector/issues/213)** short-term memory, **[#214](https://github.com/mahmoudazaid/Kernector/issues/214)** HITL, and **[#216](https://github.com/mahmoudazaid/Kernector/issues/216)** agentic RAG are **closed**; purpose brief [#212](https://github.com/mahmoudazaid/Kernector/issues/212) is written in-repo. Long-term cross-thread memory deferred to [#299](https://github.com/mahmoudazaid/Kernector/issues/299). **Max bonus (≥2 medium + 1 hard) is met** (e.g. short-term memory + Drive export + agentic RAG / external KB connectors).

---

## Summary

| Area | Count |
|------|-------|
| Mandatory Done | 4 / 5 |
| Mandatory Partial | 1 / 5 |
| Optional Done | 9 |
| Optional Partial | 4 |
| Optional Not done | 5 |
| Max bonus (≥2 medium + 1 hard) | **Met** |
| Sprint#3 tickets | 41 (9 open / 32 closed) |
| Primary agent epic | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) (open) |
| Agent loop | [#43](https://github.com/mahmoudazaid/Kernector/issues/43) (**closed**) |
| Short-term memory | [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (**closed**) |
| HITL | [#214](https://github.com/mahmoudazaid/Kernector/issues/214) (**closed**) |
| Agentic RAG | [#216](https://github.com/mahmoudazaid/Kernector/issues/216) (**closed**) |

**Agent framing:** Kernector is a **grounded RAG chatbot** with an **opt-in LangGraph ReAct loop** for Software Delivery tool turns and agent-path asks. With `SOFTWARE_DELIVERY_AGENT_LOOP=true`, pack orchestrate swaps to `LangGraphToolAgent` (`infrastructure/agents/langgraph_tool_agent.py` behind `ToolCallingAgent`; wired via `composition/software_delivery_agent.py`). Chat intent matches **Google Drive export** only (#309; scaffolding risk/generate/markdown-export retired in #285). **Agentic RAG:** `RetrieveKnowledgeTool` (`application/retrieve_knowledge_tool.py`) binds as `knowledge.retrieve`; `AskKnowledgeWithAgent` runs retrieve-then-answer with citation channel (PR [#328](https://github.com/mahmoudazaid/Kernector/pull/328)). Short-term thread memory uses process-scoped `InMemorySaver` (`composition/short_term_memory.py`) keyed `{workspace_id}:{conversation_id}`. HITL pauses allowlisted tools (Drive export) via LangGraph `interrupt()`; Next.js shows `ToolApprovalCard` for approve/reject. Response style presets (formal / friendly / concise) and thumbs feedback store are shipped. Test Design coverage planning (#293) is pack-local (not an agent `Tool`). Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211) stays open for [#215](https://github.com/mahmoudazaid/Kernector/issues/215) and bonus follow-ons.

**Domain purpose:** Software Delivery Intelligence — grounded chat over delivery knowledge, interactive test-design workflow, Drive export with HITL — target users: QA / engineering teams. Speaking brief: [`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md) ([#212](https://github.com/mahmoudazaid/Kernector/issues/212)).

**Entry (current):**

```bash
HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload
# Opt-in agent orchestrate + Drive-export intent + short-term memory + HITL + agentic retrieve:
# SOFTWARE_DELIVERY_AGENT_LOOP=true DOMAIN_TOOL_PACKS=software-delivery ...
cd web && npm ci && npm run dev   # http://localhost:3000
```

Chat / Settings / Documents: `web/app/chat`, `web/app/settings`, `web/app/documents`. Conversations: `web/app/chat/[conversationId]`.

---

## What changed since 2026-09-16

| Change | Evidence |
|--------|----------|
| **[#216](https://github.com/mahmoudazaid/Kernector/issues/216) closed** — agentic RAG retrieve in LangGraph | PR [#328](https://github.com/mahmoudazaid/Kernector/pull/328); `RetrieveKnowledgeTool`, `AskKnowledgeWithAgent`, citation channel |
| **[#218](https://github.com/mahmoudazaid/Kernector/issues/218) closed** — agent personality / response style | PR [#313](https://github.com/mahmoudazaid/Kernector/pull/313); `response_style` formal/friendly/concise in chat + agent system compose |
| **[#219](https://github.com/mahmoudazaid/Kernector/issues/219) closed** — response feedback foundation | PR [#321](https://github.com/mahmoudazaid/Kernector/pull/321); thumbs up/down → SQLite `response_feedback`; improve-from-feedback still [#223](https://github.com/mahmoudazaid/Kernector/issues/223) |
| **[#220](https://github.com/mahmoudazaid/Kernector/issues/220) closed** — generation settings UI AC | Temperature / max tokens (and related) in Settings; ticket closed |
| Earlier (still current): HITL [#214](https://github.com/mahmoudazaid/Kernector/issues/214), STM [#213](https://github.com/mahmoudazaid/Kernector/issues/213), Drive export [#197](https://github.com/mahmoudazaid/Kernector/issues/197)/[#309](https://github.com/mahmoudazaid/Kernector/issues/309) | Unchanged since prior review |

---

## Mandatory requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agent purpose (clear purpose, usefulness, target users) | Purpose | Done | [`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md); linked from README | [#212](https://github.com/mahmoudazaid/Kernector/issues/212) (`mandatory`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Core functionality (primary tasks + user interactions) | Agent | Done | RAG ask + opt-in LangGraph orchestrate ([#43](https://github.com/mahmoudazaid/Kernector/issues/43)); agentic retrieve ([#216](https://github.com/mahmoudazaid/Kernector/issues/216)); Drive export tool ([#197](https://github.com/mahmoudazaid/Kernector/issues/197)); HITL approve/reject ([#214](https://github.com/mahmoudazaid/Kernector/issues/214)); thread memory ([#213](https://github.com/mahmoudazaid/Kernector/issues/213)); Test Design workflow ([#293](https://github.com/mahmoudazaid/Kernector/issues/293)) | [#43](https://github.com/mahmoudazaid/Kernector/issues/43) / [#216](https://github.com/mahmoudazaid/Kernector/issues/216) / [#197](https://github.com/mahmoudazaid/Kernector/issues/197) / [#214](https://github.com/mahmoudazaid/Kernector/issues/214) / [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (**closed**) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| User interface (friendly UI for all functionalities) | UI | Done | Next.js chat/settings/documents; history [#246](https://github.com/mahmoudazaid/Kernector/issues/246); polish [#245](https://github.com/mahmoudazaid/Kernector/issues/245); viewer [#243](https://github.com/mahmoudazaid/Kernector/issues/243); HITL card; style picker; feedback controls; chunk inspect [#210](https://github.com/mahmoudazaid/Kernector/issues/210). Optional further UX split [#36](https://github.com/mahmoudazaid/Kernector/issues/36) still open | [#126](https://github.com/mahmoudazaid/Kernector/issues/126)/[#235](https://github.com/mahmoudazaid/Kernector/issues/235)–[#237](https://github.com/mahmoudazaid/Kernector/issues/237)/[#228](https://github.com/mahmoudazaid/Kernector/issues/228)/[#210](https://github.com/mahmoudazaid/Kernector/issues/210)/[#243](https://github.com/mahmoudazaid/Kernector/issues/243)/[#245](https://github.com/mahmoudazaid/Kernector/issues/245)/[#246](https://github.com/mahmoudazaid/Kernector/issues/246)/[#214](https://github.com/mahmoudazaid/Kernector/issues/214)/[#218](https://github.com/mahmoudazaid/Kernector/issues/218)/[#219](https://github.com/mahmoudazaid/Kernector/issues/219) (closed) | [#124](https://github.com/mahmoudazaid/Kernector/issues/124) |
| Technical implementation (tools/libs, errors, real-world use) | Technical | Done | LangChain + LangGraph adapter, OpenRouter/Ollama, `domain/errors.py`, `input_safety.py`, HITL interrupts, short-term checkpointer, retrieve tool on agent path; LT memory deferred [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | Sprint 2 carryover #89, #98, #96, #97 (closed); [#43](https://github.com/mahmoudazaid/Kernector/issues/43)/[#213](https://github.com/mahmoudazaid/Kernector/issues/213)/[#214](https://github.com/mahmoudazaid/Kernector/issues/214)/[#216](https://github.com/mahmoudazaid/Kernector/issues/216)/[#57](https://github.com/mahmoudazaid/Kernector/issues/57) (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Documentation (usage, examples, technical decisions) | Docs | Partial | `README.md`, `ARCHITECTURE.md` (agent / memory / HITL / agentic ask), ADRs; purpose brief Done ([#212](https://github.com/mahmoudazaid/Kernector/issues/212)); review-facing Sprint 3 how-to incomplete | [#215](https://github.com/mahmoudazaid/Kernector/issues/215) (open, `mandatory`); Sprint 2 #104, #105 | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#75](https://github.com/mahmoudazaid/Kernector/issues/75) |

**Gap vs 135.md topics:** LangGraph **agent loop — Done (opt-in)**. **Short-term graph memory — Done** (process-local; long-term → #299). **Human-in-the-loop — Done** for Drive export. **Agentic RAG — Done**. **Agent purpose — Done** ([`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md)). Remaining mandatory gap: review-facing agent docs ([#215](https://github.com/mahmoudazaid/Kernector/issues/215)).

---

## Optional requirements

### Easy

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| ChatGPT critique (usability / security / prompts) | Easy | Not done | — | [#217](https://github.com/mahmoudazaid/Kernector/issues/217) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Agent personality (formal / friendly / concise) | Easy | Done | `application/response_style_policy.py`; chat style control → `runtime.response_style`; agent system compose | [#218](https://github.com/mahmoudazaid/Kernector/issues/218) (**closed**, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#149](https://github.com/mahmoudazaid/Kernector/issues/149) |
| Choose from a list of LLMs | Easy | Done | OpenRouter model list + Ollama in Next.js Settings | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed); Settings UI via [#237](https://github.com/mahmoudazaid/Kernector/issues/237) (closed) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| OpenAI settings as sliders/fields (temperature, max tokens, …) | Easy | Done | `domain/model_settings.py` → settings API → `web/components/settings/SettingsPanel.tsx` | [#220](https://github.com/mahmoudazaid/Kernector/issues/220) (**closed**) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Interactive help / chatbot guide | Easy | Not done | Field-level help only | [#180](https://github.com/mahmoudazaid/Kernector/issues/180) (open, `bonus`) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) / [#124](https://github.com/mahmoudazaid/Kernector/issues/124) |

### Medium

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Token usage and costs | Medium | Partial | Tokens in chat run details; `Usage.cost` not exposed in HTTP/`run_meta` UI | #40, #49, #50 (open, `bonus`) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Long-term or short-term memory (LangChain/LangGraph) | Medium | Done | Short-term `InMemorySaver` per conversation when agent loop on; LT across threads open as [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | [#213](https://github.com/mahmoudazaid/Kernector/issues/213) (**closed**, `bonus`); related [#246](https://github.com/mahmoudazaid/Kernector/issues/246) (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| One more function tool calling an external API | Medium | Done | Google Drive **export** tool + Drive sync connector | [#197](https://github.com/mahmoudazaid/Kernector/issues/197)/[#196](https://github.com/mahmoudazaid/Kernector/issues/196)/[#254](https://github.com/mahmoudazaid/Kernector/issues/254) (closed); #198, #199 (open, `bonus`) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Auth + personalisation | Medium | Not done | Drive OAuth only; no end-user auth | [#182](https://github.com/mahmoudazaid/Kernector/issues/182) (open, `bonus`) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Feedback loop (rate responses → improve agent) | Medium | Partial | Rate/store Done (thumbs + SQLite); “improve agent from feedback” still open | [#219](https://github.com/mahmoudazaid/Kernector/issues/219) (**closed**); [#223](https://github.com/mahmoudazaid/Kernector/issues/223) (open) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| 2 extra tools (5 total) + enable/disable UI + plugin system | Medium | Partial | 1 registered SD tool (Drive export) + retrieve tool on agent path; Test Design is pack-local; pack enable via `DOMAIN_TOOL_PACKS`; no per-tool toggle / dynamic plugin UI | [#221](https://github.com/mahmoudazaid/Kernector/issues/221) (open); extras #198–#199 (open) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Multi-model support (OpenAI, Anthropic, …) | Medium | Done | OpenRouter multi-model + Ollama in Settings | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed); [#41](https://github.com/mahmoudazaid/Kernector/issues/41) still open (broader native providers) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| ≥1 security guard; separate developer settings from UX | Medium | Done | `input_safety.py`, grounded RAG policy; `/settings` vs `/chat` | [#97](https://github.com/mahmoudazaid/Kernector/issues/97) (closed); [#36](https://github.com/mahmoudazaid/Kernector/issues/36) (open — further UX split) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |

### Hard

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agentic RAG (RAG inside LangChain/LangGraph agent) | Hard | Done | `RetrieveKnowledgeTool` + `AskKnowledgeWithAgent`; agent can retrieve mid-run; citations preserved | [#216](https://github.com/mahmoudazaid/Kernector/issues/216) (**closed**, `bonus`); Sprint 2 #87, #185 (closed) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| LLM observability (LangSmith, Langfuse, …) | Hard | Not done | Structured JSON logging only (`application/observability.py`); no LangSmith/Langfuse | [#222](https://github.com/mahmoudazaid/Kernector/issues/222) (open, `bonus`); [#160](https://github.com/mahmoudazaid/Kernector/issues/160) (closed) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| AI evaluation report (Ragas / DeepEval) | Hard | Partial | Custom offline + LLM-as-Judge harness Done (`composition/evaluate.py`, `data/eval/`); not Ragas/DeepEval; live HTTP/Next.js trigger open | [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) (closed, `bonus`); [#263](https://github.com/mahmoudazaid/Kernector/issues/263), [#264](https://github.com/mahmoudazaid/Kernector/issues/264) (open, `bonus`) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Learn from user feedback (adapt capabilities) | Hard | Not done | Collection Done ([#219](https://github.com/mahmoudazaid/Kernector/issues/219)); adapt still open | [#223](https://github.com/mahmoudazaid/Kernector/issues/223) (open, `bonus`) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Integrate external data sources (APIs / websites) | Hard | Done | Google Drive sync + UI; GitHub repo + Project Issues sync | [#196](https://github.com/mahmoudazaid/Kernector/issues/196), [#254](https://github.com/mahmoudazaid/Kernector/issues/254), [#286](https://github.com/mahmoudazaid/Kernector/issues/286) (closed); [#195](https://github.com/mahmoudazaid/Kernector/issues/195) OneDrive (open) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |

---

## Epic index (Sprint 3 + carryover)

| Epic / issue | Title | State | Sprint 3 relevance |
|---|---|---|---|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | **Epic: LangGraph agent, memory, and HITL** | Open | Primary Sprint 3 epic — loop/memory/HITL/agentic RAG Done; purpose/docs + bonus open |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain agent loop for multi-step tool orchestration | **Closed** | Opt-in LangGraph orchestrate shipped |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | LangGraph short-term memory | **Closed** | Process-local checkpointer; LT → #299 |
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | HITL interrupts for tool approval | **Closed** | Drive export allowlist + Next.js card |
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216) | Agentic RAG retrieve in LangGraph | **Closed** | `knowledge.retrieve` tool + agent grounded ask |
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
| [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | Write Sprint 3 agent purpose brief | Mandatory #1 | Open (brief in [`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md)) |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain / LangGraph agent loop | Mandatory #2 | **Closed** |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | LangGraph short-term memory | Medium #2 | **Closed** |
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | HITL interrupts for tool approval | Mandatory #4 / HITL | **Closed** |
| [#215](https://github.com/mahmoudazaid/Kernector/issues/215) | Document Sprint 3 agent usage | Mandatory #5 | Open |
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216) | Agentic RAG in LangGraph | Hard #1 | **Closed** |
| [#217](https://github.com/mahmoudazaid/Kernector/issues/217) | ChatGPT critique | Easy #1 | Open |
| [#218](https://github.com/mahmoudazaid/Kernector/issues/218) | Agent personality | Easy #2 | **Closed** |
| [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | Response rating feedback foundation | Medium #5 (partial) | **Closed** |
| [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | Generation settings UI | Easy #4 | **Closed** |
| [#221](https://github.com/mahmoudazaid/Kernector/issues/221) | Tool enable/disable + plugins | Medium #6 | Open |
| [#222](https://github.com/mahmoudazaid/Kernector/issues/222) | LangSmith or Langfuse | Hard #2 | Open |
| [#223](https://github.com/mahmoudazaid/Kernector/issues/223) | Adapt capabilities from feedback | Hard #4 / Medium #5 remainder | Open |
| [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | Consent-aware long-term memory across threads | Medium #2 follow-on | Open |

### Presentation / connector / agent progress (closed since prior reviews)

| # | Title | Notes |
|---|-------|-------|
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216) | Agentic RAG | Closed 2026-09-18 — Hard #1 |
| [#218](https://github.com/mahmoudazaid/Kernector/issues/218) | Response style / personality | Closed 2026-09-17 — Easy #2 |
| [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | Feedback collection | Closed 2026-09-17 — Medium #5 Partial |
| [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | Generation settings UI | Closed 2026-09-16 — Easy #4 |
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
| [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | Agent purpose brief | Mandatory #1 — brief landed; close after merge |
| [#215](https://github.com/mahmoudazaid/Kernector/issues/215) | Agent usage docs | Mandatory #5 |
| [#217](https://github.com/mahmoudazaid/Kernector/issues/217) | ChatGPT critique | Easy #1 |
| [#221](https://github.com/mahmoudazaid/Kernector/issues/221) | Tool enable/disable + plugins | Medium #6 |
| [#222](https://github.com/mahmoudazaid/Kernector/issues/222) | LangSmith / Langfuse | Hard #2 |
| [#223](https://github.com/mahmoudazaid/Kernector/issues/223) | Adapt from feedback | Hard #4 |
| [#263](https://github.com/mahmoudazaid/Kernector/issues/263), [#264](https://github.com/mahmoudazaid/Kernector/issues/264) | Live Judge eval HTTP / settings | Bonus |
| [#299](https://github.com/mahmoudazaid/Kernector/issues/299) | Long-term memory | Follow-on from #213 |

Carryover (not all `Sprint#3`): [#36](https://github.com/mahmoudazaid/Kernector/issues/36), [#40](https://github.com/mahmoudazaid/Kernector/issues/40)/[#49](https://github.com/mahmoudazaid/Kernector/issues/49)/[#50](https://github.com/mahmoudazaid/Kernector/issues/50), [#180](https://github.com/mahmoudazaid/Kernector/issues/180), [#182](https://github.com/mahmoudazaid/Kernector/issues/182), [#198](https://github.com/mahmoudazaid/Kernector/issues/198)/[#199](https://github.com/mahmoudazaid/Kernector/issues/199), [#298](https://github.com/mahmoudazaid/Kernector/issues/298).

---

## Evaluation criteria checklist ([135.md](../135.md))

| Criterion | Ready for review? | Notes |
|-----------|-------------------|--------|
| Problem definition | Ready | [`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md) ([#212](https://github.com/mahmoudazaid/Kernector/issues/212)) |
| Understanding core concepts | Near ready | Agent loop / memory / HITL / agentic RAG in code + `ARCHITECTURE.md`; still need review-facing docs [#215](https://github.com/mahmoudazaid/Kernector/issues/215) |
| Technical implementation | Ready | Next.js UI + KB + security + LangGraph + STM + HITL + retrieve tool on `main` |
| Reflection and improvement | Not ready | [#215](https://github.com/mahmoudazaid/Kernector/issues/215) + critique [#217](https://github.com/mahmoudazaid/Kernector/issues/217) |
| Bonus (≥2 medium + 1 hard) | **Met** | Medium: STM [#213](https://github.com/mahmoudazaid/Kernector/issues/213) + Drive export [#197](https://github.com/mahmoudazaid/Kernector/issues/197) (also multi-model + security). Hard: agentic RAG [#216](https://github.com/mahmoudazaid/Kernector/issues/216) **and** external sources Drive + GitHub ([#196](https://github.com/mahmoudazaid/Kernector/issues/196)/[#254](https://github.com/mahmoudazaid/Kernector/issues/254)/[#286](https://github.com/mahmoudazaid/Kernector/issues/286)) |

---

## Suggested Sprint 3 path (remaining)

1. ~~[#212](https://github.com/mahmoudazaid/Kernector/issues/212) — write **agent purpose** brief~~ **Done** ([`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md)).
2. ~~[#43](https://github.com/mahmoudazaid/Kernector/issues/43) — LangGraph/LangChain **agent loop**~~ **Done**.
3. ~~[#213](https://github.com/mahmoudazaid/Kernector/issues/213) — short-term **memory**~~ **Done** (optional LT: [#299](https://github.com/mahmoudazaid/Kernector/issues/299)).
4. ~~[#214](https://github.com/mahmoudazaid/Kernector/issues/214) — **HITL**~~ **Done**.
5. ~~[#216](https://github.com/mahmoudazaid/Kernector/issues/216) — **agentic RAG**~~ **Done**.
6. [#215](https://github.com/mahmoudazaid/Kernector/issues/215) — agent **docs** for review (flag, demo steps, architecture).
7. ~~UI polish / personality / feedback / settings~~ **Done** ([#245](https://github.com/mahmoudazaid/Kernector/issues/245)/[#218](https://github.com/mahmoudazaid/Kernector/issues/218)/[#219](https://github.com/mahmoudazaid/Kernector/issues/219)/[#220](https://github.com/mahmoudazaid/Kernector/issues/220)).
8. Demo on **Next.js** (`web/` + FastAPI); Streamlit is retired.
9. Optional further bonus: observability [#222](https://github.com/mahmoudazaid/Kernector/issues/222), adapt-from-feedback [#223](https://github.com/mahmoudazaid/Kernector/issues/223), more tools [#198](https://github.com/mahmoudazaid/Kernector/issues/198)/[#221](https://github.com/mahmoudazaid/Kernector/issues/221), critique [#217](https://github.com/mahmoudazaid/Kernector/issues/217).

---

## Demo checklist (target for Sprint 3 review)

1. State agent purpose and users in one minute — [`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md) ([#212](https://github.com/mahmoudazaid/Kernector/issues/212)).
2. Show agent graph (or architecture diagram): nodes, state, tools ([#43](https://github.com/mahmoudazaid/Kernector/issues/43) — via `SOFTWARE_DELIVERY_AGENT_LOOP=true`).
3. Run a Drive-export tool turn on the agent path (intent + prepared call + HITL).
4. Show short-term memory: follow-up in the same conversation_id uses checkpoint ([#213](https://github.com/mahmoudazaid/Kernector/issues/213)).
5. HITL: pause before Drive export; approve/reject in Next.js ([#214](https://github.com/mahmoudazaid/Kernector/issues/214)).
6. Agentic RAG: agent invokes `knowledge.retrieve` mid-run; citations visible ([#216](https://github.com/mahmoudazaid/Kernector/issues/216)).
7. Response style presets + thumbs feedback ([#218](https://github.com/mahmoudazaid/Kernector/issues/218)/[#219](https://github.com/mahmoudazaid/Kernector/issues/219)).
8. Optional: tokens/cost, observability ([#40](https://github.com/mahmoudazaid/Kernector/issues/40), [#222](https://github.com/mahmoudazaid/Kernector/issues/222)).
9. Show Next.js chat + history + Settings + Documents (chunk inspect [#210](https://github.com/mahmoudazaid/Kernector/issues/210); viewer [#243](https://github.com/mahmoudazaid/Kernector/issues/243); Drive/GitHub sync for Hard #5).

Until review-facing agent docs land ([#215](https://github.com/mahmoudazaid/Kernector/issues/215)), use [`sprint-3-agent-purpose.md`](sprint-3-agent-purpose.md) for the one-minute pitch, `ARCHITECTURE.md` for agent/memory/HITL/agentic-ask detail, and [`sprint-2-project-review-guide.md`](sprint-2-project-review-guide.md) for the Sprint 2 RAG baseline (run against Next.js, not Streamlit).
