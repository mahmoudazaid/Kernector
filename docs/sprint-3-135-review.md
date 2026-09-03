# Sprint 3 (135.md) — Requirements Review

**Project:** Kernector  
**Spec:** [`135.md`](../135.md)  
**Prior sprint:** [`sprint-2-125-review.md`](sprint-2-125-review.md)  
**Review date:** 2026-09-03  
**Verdict:** **Baseline gap review.** Sprint 2 RAG + tools + Streamlit are in place; Sprint 3 **LangGraph agent**, **memory**, and **HITL** work is **not started**. Gap tickets created under Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211). Max bonus (≥2 medium + 1 hard) not met yet — pick after agent MVP.

---

## Summary

| Area | Count |
|------|-------|
| Mandatory Done | 0 / 5 |
| Mandatory Partial (Sprint 2 carryover) | 5 / 5 |
| Optional Done (carryover) | 4 |
| Optional Partial | 3 |
| Optional Not done | 11 |
| Max bonus (≥2 medium + 1 hard) | Not met yet |
| New Sprint 3 tickets (this pass) | 13 (#211–#223) |

**Agent framing:** Kernector today is a **grounded RAG chatbot** with **intent-routed domain tools**, not a LangGraph/LangChain **agent loop** (state, multi-step tool planning, checkpoints, interrupts). Sprint 3 needs an explicit agent architecture on top of (or replacing parts of) that path — tracked by Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211) and agent loop [#43](https://github.com/mahmoudazaid/Kernector/issues/43).

**Domain purpose (proposed carryover):** Software Delivery Intelligence — risk scoring, grounded test-case generation/export, RAG over delivery knowledge — target users: QA / engineering teams. Formal brief: [#212](https://github.com/mahmoudazaid/Kernector/issues/212).

**Entry (current):** `uv run streamlit run main.py` → `presentation/streamlit/app.py` `render()`. Next.js shell in progress under `web/` ([#126](https://github.com/mahmoudazaid/Kernector/issues/126)).

---

## Mandatory requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agent purpose (clear purpose, usefulness, target users) | Purpose | Partial | README / `packs/software_delivery/`; Sprint 3 brief pending | [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Core functionality (primary tasks + user interactions) | Agent | Partial | RAG ask + SD tools via `composition/tool_augmented_ask.py`, `packs/software_delivery/orchestration.py` — **no** LangGraph agent loop | [#43](https://github.com/mahmoudazaid/Kernector/issues/43) (open; agent loop) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| User interface (friendly UI for all functionalities) | UI | Partial | Streamlit Done (`presentation/streamlit/`); Next.js shell WIP (`web/`); HITL UI [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | [#34](https://github.com/mahmoudazaid/Kernector/issues/34) (closed); [#126](https://github.com/mahmoudazaid/Kernector/issues/126), [#124](https://github.com/mahmoudazaid/Kernector/issues/124) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) / [#124](https://github.com/mahmoudazaid/Kernector/issues/124) |
| Technical implementation (tools/libs, errors, real-world use) | Technical | Partial | LangChain + OpenRouter/Ollama, `domain/errors.py`, `input_safety.py`; missing LangGraph state/memory/HITL | #89, #98, #96, #97 (Sprint 2); [#213](https://github.com/mahmoudazaid/Kernector/issues/213), [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Documentation (usage, examples, technical decisions) | Docs | Partial | `README.md`, `ARCHITECTURE.md`, ADRs; agent how-to incomplete | [#215](https://github.com/mahmoudazaid/Kernector/issues/215); also #104, #105 | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#75](https://github.com/mahmoudazaid/Kernector/issues/75) |

**Gap vs 135.md topics:** LangGraph/LangChain agents, long-term/short-term memory, human-in-the-loop — **not implemented**. Tool calling remains intent-routed (`chat_intent.py`), not native agent function calling inside a graph.

---

## Optional requirements

### Easy

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| ChatGPT critique (usability / security / prompts) | Easy | Not done | — | [#217](https://github.com/mahmoudazaid/Kernector/issues/217) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Agent personality (formal / friendly / concise) | Easy | Not done | — | [#218](https://github.com/mahmoudazaid/Kernector/issues/218) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#149](https://github.com/mahmoudazaid/Kernector/issues/149) |
| Choose from a list of LLMs | Easy | Done | OpenRouter model list + Ollama; `available_providers` | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| OpenAI settings as sliders/fields (temperature, max tokens, …) | Easy | Partial | Some settings widgets in `components.py`; not full user-facing OpenAI dials | [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Interactive help / chatbot guide | Easy | Not done | — | [#180](https://github.com/mahmoudazaid/Kernector/issues/180) (open) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |

### Medium

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Token usage and costs | Medium | Partial | tokens in `run_details.py`; cost not shown in UI | #40, #49, #50 (open) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Long-term or short-term memory (LangChain/LangGraph) | Medium | Not done | session chat history only in Streamlit; no graph memory / store | [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| One more function tool calling an external API | Medium | Not done | SD tools are local/pack; Drive/OneDrive/Xray tickets open | #197, #198, #199 (open) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Auth + personalisation | Medium | Not done | — | [#182](https://github.com/mahmoudazaid/Kernector/issues/182) (open) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Feedback loop (rate responses → improve agent) | Medium | Not done | — | [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| 2 extra tools (5 total) + enable/disable UI + plugin system | Medium | Partial | 3 SD tools Done; no dynamic enable/disable plugin UI | [#221](https://github.com/mahmoudazaid/Kernector/issues/221); extras #197–#199 | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Multi-model support (OpenAI, Anthropic, …) | Medium | Done | OpenRouter multi-model + Ollama | [#39](https://github.com/mahmoudazaid/Kernector/issues/39); [#41](https://github.com/mahmoudazaid/Kernector/issues/41) still open (broader native) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| ≥1 security guard; separate developer settings from UX | Medium | Done | `input_safety.py`, grounded RAG policy; sidebar settings vs chat | [#97](https://github.com/mahmoudazaid/Kernector/issues/97) (closed); [#36](https://github.com/mahmoudazaid/Kernector/issues/36) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |

### Hard

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Agentic RAG (RAG inside LangChain/LangGraph agent) | Hard | Partial | Advanced RAG Done (rewrite/retrieve, hybrid); **not** agentic graph RAG | [#216](https://github.com/mahmoudazaid/Kernector/issues/216); Sprint 2 #87, #185 | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) / [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| LLM observability (LangSmith, Langfuse, …) | Hard | Partial | structured logging (`observability.py`); not LangSmith/Langfuse | [#222](https://github.com/mahmoudazaid/Kernector/issues/222); [#160](https://github.com/mahmoudazaid/Kernector/issues/160) (closed) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| AI evaluation report (Ragas / DeepEval) | Hard | Not done | — | [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) (open) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Learn from user feedback (adapt capabilities) | Hard | Not done | — | [#223](https://github.com/mahmoudazaid/Kernector/issues/223) (depends on #219) | [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Integrate external data sources (APIs / websites) | Hard | Not done | planned connectors; not shipped | #195, #196 (open) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |

---

## Epic index (Sprint 3 + carryover)

| Epic / issue | Title | Sprint 3 relevance |
|------|-------|-------------------|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | **Epic: LangGraph agent, memory, and HITL (Sprint 3)** | Primary Sprint 3 epic |
| [#43](https://github.com/mahmoudazaid/Kernector/issues/43) | LangChain agent loop for multi-step tool orchestration | Core agent delivery (parent still #9; linked from #211) |
| [#9](https://github.com/mahmoudazaid/Kernector/issues/9) | Software Delivery Intelligence domain pack | Agent domain / tools / plugins |
| [#68](https://github.com/mahmoudazaid/Kernector/issues/68) | Generic Knowledge Foundation | External sources |
| [#70](https://github.com/mahmoudazaid/Kernector/issues/70) | RAG Orchestration | Grounded retrieve path |
| [#72](https://github.com/mahmoudazaid/Kernector/issues/72) | Security | Guards + auth optional |
| [#73](https://github.com/mahmoudazaid/Kernector/issues/73) / [#124](https://github.com/mahmoudazaid/Kernector/issues/124) | UI / Next.js migration | Streamlit or Next.js UI |
| [#74](https://github.com/mahmoudazaid/Kernector/issues/74) | Quality / Evaluation | Ragas / Langfuse hard options |
| [#75](https://github.com/mahmoudazaid/Kernector/issues/75) | Documentation | Ops / architecture docs |
| [#148](https://github.com/mahmoudazaid/Kernector/issues/148) | Model Runtime and Provider Experience | LLM list / tokens / settings |

### New tickets created (2026-09-03)

| # | Title | Maps to |
|---|-------|---------|
| [#211](https://github.com/mahmoudazaid/Kernector/issues/211) | Epic: LangGraph agent, memory, and HITL | Sprint 3 foundation |
| [#212](https://github.com/mahmoudazaid/Kernector/issues/212) | Write Sprint 3 agent purpose brief | Mandatory #1 |
| [#213](https://github.com/mahmoudazaid/Kernector/issues/213) | Add LangGraph short-term and long-term memory | Medium #2 |
| [#214](https://github.com/mahmoudazaid/Kernector/issues/214) | Add human-in-the-loop interrupts for tool approval | HITL / technical |
| [#215](https://github.com/mahmoudazaid/Kernector/issues/215) | Document Sprint 3 agent usage, examples, decisions | Mandatory #5 |
| [#216](https://github.com/mahmoudazaid/Kernector/issues/216) | Wire agentic RAG retrieve into the LangGraph agent | Hard #1 |
| [#217](https://github.com/mahmoudazaid/Kernector/issues/217) | Capture ChatGPT critique | Easy #1 |
| [#218](https://github.com/mahmoudazaid/Kernector/issues/218) | Add selectable agent personality | Easy #2 |
| [#219](https://github.com/mahmoudazaid/Kernector/issues/219) | Add response rating feedback loop | Medium #5 |
| [#220](https://github.com/mahmoudazaid/Kernector/issues/220) | Expose generation settings in the UI | Easy #4 (follow-up) |
| [#221](https://github.com/mahmoudazaid/Kernector/issues/221) | Tool enable/disable UI + dynamic pack plugins | Medium #6 (follow-up) |
| [#222](https://github.com/mahmoudazaid/Kernector/issues/222) | Integrate LangSmith or Langfuse | Hard #2 (follow-up) |
| [#223](https://github.com/mahmoudazaid/Kernector/issues/223) | Adapt agent capabilities from user feedback | Hard #4 |

---

## Evaluation criteria checklist (135.md)

| Criterion | Ready for review? | Notes |
|-----------|-------------------|--------|
| Problem definition | Partial | SD domain clear; brief [#212](https://github.com/mahmoudazaid/Kernector/issues/212) |
| Understanding core concepts | Not ready | Agent docs [#215](https://github.com/mahmoudazaid/Kernector/issues/215) + agent loop [#43](https://github.com/mahmoudazaid/Kernector/issues/43) |
| Technical implementation | Partial | Front-end + KB + security exist; agent stack [#211](https://github.com/mahmoudazaid/Kernector/issues/211) |
| Reflection and improvement | Not ready | Covered in [#215](https://github.com/mahmoudazaid/Kernector/issues/215) + critique [#217](https://github.com/mahmoudazaid/Kernector/issues/217) |
| Bonus (≥2 medium + 1 hard) | Not met | Candidates: [#213](https://github.com/mahmoudazaid/Kernector/issues/213) + external API tool + [#216](https://github.com/mahmoudazaid/Kernector/issues/216) / [#222](https://github.com/mahmoudazaid/Kernector/issues/222) |

---

## Suggested Sprint 3 path

1. [#212](https://github.com/mahmoudazaid/Kernector/issues/212) — write **agent purpose** brief.
2. [#43](https://github.com/mahmoudazaid/Kernector/issues/43) — LangGraph/LangChain **agent loop** (under Epic [#211](https://github.com/mahmoudazaid/Kernector/issues/211)).
3. [#213](https://github.com/mahmoudazaid/Kernector/issues/213) — **memory** (checkpoint / optional long-term store).
4. [#214](https://github.com/mahmoudazaid/Kernector/issues/214) — **HITL** for high-impact tools.
5. [#215](https://github.com/mahmoudazaid/Kernector/issues/215) — agent **docs** for review.
6. Keep Streamlit as review UI until Next.js chat parity; or demo Next.js shell + HTTP when `#81` lands.
7. Choose **≥2 medium + 1 hard** for max bonus (e.g. #213 + #197/#199 + #216 or #222).

---

## Demo checklist (target for Sprint 3 review)

1. State agent purpose and users in one minute ([#212](https://github.com/mahmoudazaid/Kernector/issues/212)).
2. Show agent graph (or architecture diagram): nodes, state, tools ([#43](https://github.com/mahmoudazaid/Kernector/issues/43)).
3. Run a multi-step task that needs ≥2 tool calls without manual intent keywords if agent-driven.
4. Show memory: follow-up turn uses prior context / checkpoint ([#213](https://github.com/mahmoudazaid/Kernector/issues/213)).
5. Optional HITL: pause before a risky tool; approve/reject ([#214](https://github.com/mahmoudazaid/Kernector/issues/214)).
6. Optional: agentic RAG retrieve inside the graph; citations still visible ([#216](https://github.com/mahmoudazaid/Kernector/issues/216)).
7. Optional: tokens/cost, model picker, observability ([#220](https://github.com/mahmoudazaid/Kernector/issues/220), [#222](https://github.com/mahmoudazaid/Kernector/issues/222)).

Until the agent path exists, use [`sprint-2-project-review-guide.md`](sprint-2-project-review-guide.md) only for the Sprint 2 baseline demo.
