# Sprint 2 (125.md) — Requirements Review

**Project:** Kernector  
**Spec:** [`125.md`](../125.md)  
**Companion:** [`sprint-2-project-review-guide.md`](sprint-2-project-review-guide.md) (demo script + architecture talking points)  
**Review date:** 2026-09-03  
**Verdict:** All **mandatory** requirements are **Done**. Max bonus met. Ready for Sprint 2 project review.

---

## Summary

| Area | Count |
|------|-------|
| Mandatory Done | 16 / 16 |
| Optional Done | 10 |
| Optional Partial | 1 |
| Optional Not done | 10 |
| Max bonus (≥2 medium + 1 hard) | Met (medium × several + hybrid hard #185) |

**Note:** Tool calling is intent-routed (`#170`, closed), not LLM native `bind_tools` / function calling. Valid for 125.md; explain at review via `packs/software_delivery/chat_intent.py` → `composition/tool_augmented_ask.py`.

**Entry:** `uv run streamlit run main.py` → `presentation/streamlit/app.py` `render()`.

---

## Mandatory requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Domain knowledge base | RAG | Done | `data/knowledge/`, `infrastructure/knowledge/corpus.py` | #82, #117, #137 | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Embeddings + retrieval | RAG | Done | `infrastructure/embeddings/openrouter.py`, `application/retrieve_knowledge.py` | #86 | [#69](https://github.com/mahmoudazaid/Kernector/issues/69) |
| Chunking strategies | RAG | Done | `application/chunking.py`, `application/ingest_knowledge.py` | #83, #85 | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Similarity search | RAG | Done | `infrastructure/vectorstore/chroma.py` | #84 | [#69](https://github.com/mahmoudazaid/Kernector/issues/69) |
| Advanced RAG / query translation | RAG | Done | `application/rewrite_and_retrieve.py`, `infrastructure/llm/query_rewrite.py` | #87 | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| ≥3 domain tool calls | Tool | Done | `packs/software_delivery/{risk_score,generate_test_cases,export_test_cases_markdown}_tool.py`, `orchestration.py` | #92, #93, #94, #95 | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) / [#71](https://github.com/mahmoudazaid/Kernector/issues/71) |
| Chat-time tool selection | Tool | Done | `packs/software_delivery/chat_intent.py`, `composition/tool_augmented_ask.py` | [#170](https://github.com/mahmoudazaid/Kernector/issues/170) (closed) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Domain focus + prompts | Domain | Done | `packs/software_delivery/`, `prompts/packs/` | #90, #136, #139 | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Domain security measures | Domain | Done | `application/input_safety.py`, `grounded_rag_policy.py` | #97, #22 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| LangChain + OpenRouter | Technical | Done | `infrastructure/llm/openrouter.py`, `pyproject.toml` | #89 | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| Error handling | Technical | Done | `domain/errors.py`, `presentation/streamlit/ask_turn.py` | #98 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Input validation | Technical | Done | `application/contracts.py`, `input_safety.py` | #96 | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Streamlit UI | UI | Done | `presentation/streamlit/app.py` | [#34](https://github.com/mahmoudazaid/Kernector/issues/34) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Show context / sources | UI | Done | `application/citations.py`, `_render_citations` in `app.py` | [#88](https://github.com/mahmoudazaid/Kernector/issues/88) (closed) | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| Display tool call results | UI | Done | `projected_results.py`, `tool_run_panel.py`, `app.py` | [#178](https://github.com/mahmoudazaid/Kernector/issues/178) (closed) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Progress indicators | UI | Done | `st.spinner("Thinking...")` in `app.py` | — | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |

---

## Optional requirements

| Requirement | type | status | location | ticket | epic |
|---|---|---|---|---|---|
| Conversation history + export | Easy | Done | `app.py` `_render_history`; test-case MD/JSON/CSV/PDF via `render_test_cases_export_actions` | #34, [#181](https://github.com/mahmoudazaid/Kernector/issues/181) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Visualise RAG process | Easy | Done | `run_details.py` (query rewritten, hits, citations, latency, tokens) | [#179](https://github.com/mahmoudazaid/Kernector/issues/179) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Source citations | Easy | Done | `application/citations.py` | [#88](https://github.com/mahmoudazaid/Kernector/issues/88) (closed) | [#70](https://github.com/mahmoudazaid/Kernector/issues/70) |
| Interactive help / guide | Easy | Not done | — | [#180](https://github.com/mahmoudazaid/Kernector/issues/180) (open) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Multi-model support | Medium | Done | OpenRouter model list + Ollama in `app.py` / `composition/container.py` (`available_providers`) | [#39](https://github.com/mahmoudazaid/Kernector/issues/39) (closed); [#41](https://github.com/mahmoudazaid/Kernector/issues/41) still open (broader native providers) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Real-time KB updates | Medium | Done | `upload_ingest.py`, `manage_documents.py` | [#120](https://github.com/mahmoudazaid/Kernector/issues/120), [#122](https://github.com/mahmoudazaid/Kernector/issues/122) (closed) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Prompt injection protection | Medium | Done | `application/input_safety.py` | [#97](https://github.com/mahmoudazaid/Kernector/issues/97) (closed) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Auth + personalisation | Medium | Not done | — | [#182](https://github.com/mahmoudazaid/Kernector/issues/182) (open) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Token usage and costs | Medium | Partial | tokens in `run_details.py`; `Usage.cost` on domain model / providers, not shown in UI | [#40](https://github.com/mahmoudazaid/Kernector/issues/40), [#49](https://github.com/mahmoudazaid/Kernector/issues/49), [#50](https://github.com/mahmoudazaid/Kernector/issues/50) (open) | [#148](https://github.com/mahmoudazaid/Kernector/issues/148) |
| Tool-result visualisation | Medium | Done | `tool_run_panel.py` via `projected_results.py` | [#178](https://github.com/mahmoudazaid/Kernector/issues/178) (closed) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Export PDF / CSV / JSON | Medium | Done | `cases_export.py`, `components.render_test_cases_export_actions`, `composition/conversation_export.py` → PDF helper (test-case export; not full-chat transcript) | [#181](https://github.com/mahmoudazaid/Kernector/issues/181) (closed) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Remote MCP tools | Medium | Not done | — | [#184](https://github.com/mahmoudazaid/Kernector/issues/184) (open) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| Rate limiting + API keys | Medium | Not done | — | [#183](https://github.com/mahmoudazaid/Kernector/issues/183) (open; + #20) | [#72](https://github.com/mahmoudazaid/Kernector/issues/72) |
| Logging and monitoring | Medium | Done | `application/observability.py`, `composition/logging_config.py` | [#160](https://github.com/mahmoudazaid/Kernector/issues/160) (closed) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Hybrid search | Hard | Done | `application/hybrid_fusion.py`, `infrastructure/vectorstore/dual_write.py`, `infrastructure/lexical/bm25.py`; `HYBRID_SEARCH_ENABLED` / `HYBRID_ALPHA` | [#185](https://github.com/mahmoudazaid/Kernector/issues/185) (closed) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| A/B testing RAG | Hard | Not done | — | [#186](https://github.com/mahmoudazaid/Kernector/issues/186) (open) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Automated KB updates | Hard | Not done | — | [#187](https://github.com/mahmoudazaid/Kernector/issues/187) (open) | [#68](https://github.com/mahmoudazaid/Kernector/issues/68) |
| Multi-language | Hard | Not done | — | [#188](https://github.com/mahmoudazaid/Kernector/issues/188) (open) | [#73](https://github.com/mahmoudazaid/Kernector/issues/73) |
| Analytics dashboard | Hard | Not done | — | [#189](https://github.com/mahmoudazaid/Kernector/issues/189) (open) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |
| Tools as MCP servers | Hard | Not done | — | [#190](https://github.com/mahmoudazaid/Kernector/issues/190) (open) | [#9](https://github.com/mahmoudazaid/Kernector/issues/9) |
| RAG evaluation | Hard | Not done | — | [#102](https://github.com/mahmoudazaid/Kernector/issues/102), [#106](https://github.com/mahmoudazaid/Kernector/issues/106) (open) | [#74](https://github.com/mahmoudazaid/Kernector/issues/74) |

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

1. Ingest or upload a document → confirm chunks in catalog (`upload_ingest.py`).
2. Ask a grounded question → Citations expander + Run details (query rewritten / hits / citations / tokens / latency).
3. **General** mode: trigger Software Delivery tools (risk score, generate tests → markdown export) → typed panels + MD/JSON/CSV/PDF downloads.
4. Optional: `HYBRID_SEARCH_ENABLED=true` → exact-token retrieve; mention BM25 + vector fusion (`hybrid_fusion.py`).
5. Switch OpenRouter / Ollama model → Run details shows model + tokens.
6. Mention intent-based tool routing vs native function calling if asked.

Full prompts and expect/do-not-trigger examples: [`sprint-2-project-review-guide.md`](sprint-2-project-review-guide.md) §3–4.
