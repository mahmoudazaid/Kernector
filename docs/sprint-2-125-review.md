# Sprint 2 (125.md) — Requirements Review

**Project:** Kernector  
**Spec:** `125.md`  
**Review date:** 2026-09-02  
**Verdict:** All **mandatory** requirements are **Done**. Ready for Sprint 2 project review.

---

## Summary

| Area | Count |
|------|-------|
| Mandatory Done | 16 / 16 |
| Optional Done | 9 |
| Optional Partial | 1 |
| Optional Not done | 11 |
| Max bonus (≥2 medium + 1 hard) | Medium met; no hard optional done |

**Note:** Tool calling is intent-routed (`#170`), not LLM native `bind_tools` / function calling. Valid for 125.md; be ready to explain at review.

---

## Mandatory requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Domain knowledge base | RAG | Done | `data/knowledge/`, `infrastructure/knowledge/corpus.py` | #82, #117, #137 | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Embeddings + retrieval | RAG | Done | `infrastructure/embeddings/openrouter.py`, `application/retrieve_knowledge.py` | #86 | [#69](https://github.com/mahmoudazaid/Kernector/issues/69) |
| Chunking strategies | RAG | Done | `application/chunking.py`, `application/ingest_knowledge.py` | #83, #85 | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Similarity search | RAG | Done | `infrastructure/vectorstore/chroma.py` | #84 | [#69](https://github.com/mahmoudazaid/Kernector/issues/69) |
| Advanced RAG / query translation | RAG | Done | `application/rewrite_and_retrieve.py`, `infrastructure/llm/query_rewrite.py` | #87 | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| ≥3 domain tool calls | Tool | Done | `packs/software_delivery/*_tool.py`, `orchestration.py` | #92, #93, #94, #95 | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) / [#71](https://github.com/mahmoudazaid/Kernector/issues/71) |
| Chat-time tool selection | Tool | Done | `packs/software_delivery/chat_intent.py`, `composition/tool_augmented_ask.py` | #170 | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Domain focus + prompts | Domain | Done | `packs/software_delivery/`, `prompts/packs/` | #90, #136, #139 | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Domain security measures | Domain | Done | `application/input_safety.py`, `grounded_rag_policy.py` | #97, #22 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| LangChain + OpenRouter | Technical | Done | `infrastructure/llm/openrouter.py`, `pyproject.toml` | #89 | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| Error handling | Technical | Done | `domain/errors.py`, `presentation/streamlit/ask_turn.py` | #98 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Input validation | Technical | Done | `application/contracts.py`, `input_safety.py` | #96 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Streamlit UI | UI | Done | `presentation/streamlit/app.py` | #34 | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Show context / sources | UI | Done | `application/citations.py`, `_render_citations` | #88 | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| Display tool call results | UI | Done | `projected_results.py`, `tool_run_panel.py`, `app.py` | [#178](https://github.com/mahmoudazaid/Kernector/issues/178) (closed) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Progress indicators | UI | Done | `st.spinner("Thinking...")` in `app.py` | — | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |

---

## Optional requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Conversation history + export | Easy | Done | `app.py` history; test-case MD/JSON/CSV/PDF via `render_test_cases_export_actions` | #34, [#181](https://github.com/mahmoudazaid/Kernector/issues/181) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Visualise RAG process | Easy | Done | `run_details.py` (query rewritten, hits, citations) | [#179](https://github.com/mahmoudazaid/Kernector/issues/179) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Source citations | Easy | Done | `application/citations.py` | #88 | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| Interactive help / guide | Easy | Not done | — | [#180](https://github.com/mahmoudazaid/Kernector/issues/180) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Multi-model support | Medium | Done | OpenRouter + Ollama in `app.py` | #41, #39 | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Real-time KB updates | Medium | Done | `upload_ingest.py`, `manage_documents.py` | #120, #122 | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Prompt injection protection | Medium | Done | `application/input_safety.py` | #97 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Auth + personalisation | Medium | Not done | — | [#182](https://github.com/mahmoudazaid/Kernector/issues/182) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Token usage and costs | Medium | Partial | tokens in `run_details.py`; `Usage.cost` exists but not shown | [#40](https://github.com/mahmoudazaid/Kernector/issues/40), [#49](https://github.com/mahmoudazaid/Kernector/issues/49), [#50](https://github.com/mahmoudazaid/Kernector/issues/50) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Tool-result visualisation | Medium | Done | `tool_run_panel.py` via `projected_results.py` | [#178](https://github.com/mahmoudazaid/Kernector/issues/178) (closed) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Export PDF / CSV / JSON | Medium | Done | `cases_export.py`, `components.render_test_cases_export_actions`, `conversation_transcript_pdf.py` (test-case export; not full-chat transcript) | [#181](https://github.com/mahmoudazaid/Kernector/issues/181) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Remote MCP tools | Medium | Not done | — | [#184](https://github.com/mahmoudazaid/Kernector/issues/184) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Rate limiting + API keys | Medium | Not done | — | [#183](https://github.com/mahmoudazaid/Kernector/issues/183) (+ #20) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Logging and monitoring | Medium | Done | `application/observability.py` | #160 | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Hybrid search | Hard | Not done | — | [#185](https://github.com/mahmoudazaid/Kernector/issues/185) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| A/B testing RAG | Hard | Not done | — | [#186](https://github.com/mahmoudazaid/Kernector/issues/186) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Automated KB updates | Hard | Not done | — | [#187](https://github.com/mahmoudazaid/Kernector/issues/187) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Multi-language | Hard | Not done | — | [#188](https://github.com/mahmoudazaid/Kernector/issues/188) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Analytics dashboard | Hard | Not done | — | [#189](https://github.com/mahmoudazaid/Kernector/issues/189) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Tools as MCP servers | Hard | Not done | — | [#190](https://github.com/mahmoudazaid/Kernector/issues/190) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| RAG evaluation | Hard | Not done | — | [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |

---

## Epic index

| Epic | Title |
|------|-------|
| [#9](https://github.com/mahmoudazaid/Kernector/issues/9) | Software Delivery Intelligence domain pack |
| [#68](https://github.com/mahmoudazaid/Kernector/issues/68) | Generic Knowledge Foundation |
| [#69](https://github.com/mahmoudazaid/Kernector/issues/69) | Retrieval (Sprint 2) |
| [#70](https://github.com/mahmoudazaid/Kernector/issues/70) | RAG Orchestration (Sprint 2) |
| [#71](https://github.com/mahmoudazaid/Kernector/issues/71) | Tool Calling (Sprint 2) |
| [#72](https://github.com/mahmoudazaid/Kernector/issues/72) | Security (Sprint 2) |
| [#73](https://github.com/mahmoudazaid/Kernector/issues/73) | Replaceable UI and Branding (Sprint 2) |
| [#74](https://github.com/mahmoudazaid/Kernector/issues/74) | Quality / Evaluation (Sprint 2) |
| [#148](https://github.com/mahmoudazaid/Kernector/issues/148) | Model Runtime and Provider Experience |

---

## Demo checklist for review

1. Ingest or upload a document → confirm chunks in catalog.
2. Ask a grounded question → show citations expander + Run details (query rewritten / hits / citations).
3. Trigger each Software Delivery tool (risk score, test cases, markdown export) → show typed panels + MD/JSON/CSV/PDF downloads.
4. Show Run details (latency, tokens, hits, tools).
5. Mention intent-based tool routing vs native function calling if asked.
