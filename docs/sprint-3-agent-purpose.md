# Sprint 3 — Agent purpose brief

**Project:** Kernector  
**Spec:** [`135.md`](../135.md) §1 Agent Purpose · checklist: [`sprint-3-135-review.md`](sprint-3-135-review.md)  
**Ticket:** [#212](https://github.com/mahmoudazaid/Kernector/issues/212)  
**Audience:** You + the project reviewer (~1 minute)

---

## Problem

QA and engineering teams work from delivery knowledge scattered across uploads, Drive, and GitHub Issues. They need answers that cite that corpus, help turning Issue evidence into test coverage, and a safe way to export selected test titles to Drive — without invented facts or silent high-impact tool runs.

## Purpose

Kernector’s Sprint 3 agent is **Software Delivery Intelligence**: grounded RAG chat over workspace knowledge, with an **opt-in LangGraph ReAct loop** (`SOFTWARE_DELIVERY_AGENT_LOOP=true`) for tool turns (Google Drive export and agentic `knowledge.retrieve`), plus a pack-local Test Design workflow ([#293](https://github.com/mahmoudazaid/Kernector/issues/293)). The platform core stays domain-agnostic; Software Delivery meaning lives in [`packs/software_delivery/`](../packs/software_delivery/).

## Why it is useful

- **Cited answers** from uploads, Google Drive, and GitHub — provenance stays on each hit.
- **Test Design** from a live GitHub Issue: suggest coverage candidates, confirm selection, then export.
- **Drive export with HITL** — LangGraph pauses allowlisted tools; Next.js `ToolApprovalCard` for approve/reject.
- **Short-term thread memory** — follow-ups in the same conversation reuse the checkpoint.
- **Agentic retrieve** — the agent can call `knowledge.retrieve` mid-run and surface citations.
- Response style presets (formal / friendly / concise) and thumbs feedback.

## Target users

**QA engineers** and **software engineers** on delivery teams — not a general consumer chatbot.

## Entry (demo)

```bash
HTTP_DEV_CORS=true SOFTWARE_DELIVERY_AGENT_LOOP=true DOMAIN_TOOL_PACKS=software-delivery \
  uv run uvicorn presentation.http.app:app --reload
cd web && npm ci && npm run dev   # http://localhost:3000
```

## Deeper reading

- Architecture (agent / memory / HITL / agentic ask): [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Pack capabilities: [`packs/software_delivery/README.md`](../packs/software_delivery/README.md)
- Sprint 3 checklist: [`sprint-3-135-review.md`](sprint-3-135-review.md)
- Usage / examples / decisions (mandatory #5): [`sprint-3-agent-usage.md`](sprint-3-agent-usage.md) ([#215](https://github.com/mahmoudazaid/Kernector/issues/215))
