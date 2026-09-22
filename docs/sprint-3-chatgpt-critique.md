# Sprint 3 — ChatGPT critique (usability, security, prompts)

**Ticket:** [#217](https://github.com/mahmoudazaid/Kernector/issues/217)  
**Spec:** [`135.md`](../135.md) Optional → Easy #1  
**Review type:** Static repository review (code + docs), not a penetration test or interactive usability study  
**Reviewed commit:** [`567adec2e93295b0c717c20365dec41903c07d66`](https://github.com/mahmoudazaid/Kernector/commit/567adec2e93295b0c717c20365dec41903c07d66)

---

## 1. Review scope

Inspected current sources (not issue text alone):

| Area | Paths |
| --- | --- |
| Product docs | [`README.md`](../README.md), [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`docs/sprint-3-agent-usage.md`](sprint-3-agent-usage.md) |
| Prompt / safety policy | [`application/input_safety.py`](../application/input_safety.py), [`application/grounded_rag_policy.py`](../application/grounded_rag_policy.py), [`application/untrusted_text.py`](../application/untrusted_text.py), [`application/turn_routing.py`](../application/turn_routing.py), [`application/response_style_policy.py`](../application/response_style_policy.py), [`application/citations.py`](../application/citations.py) |
| HTTP surface | [`presentation/http/app.py`](../presentation/http/app.py), [`presentation/http/schemas.py`](../presentation/http/schemas.py), [`presentation/http/errors.py`](../presentation/http/errors.py) |
| Chat UI / client storage | [`web/components/chat/ChatPanel.tsx`](../web/components/chat/ChatPanel.tsx), [`web/lib/chat/sanitize.ts`](../web/lib/chat/sanitize.ts), [`web/lib/session/conversations.ts`](../web/lib/session/conversations.ts) |
| Connector OAuth | [`infrastructure/connectors/github/oauth.py`](../infrastructure/connectors/github/oauth.py), [`infrastructure/connectors/google_drive/oauth.py`](../infrastructure/connectors/google_drive/oauth.py) (+ related composition tests) |

---

## 2. Executive conclusion

Kernector is in good shape as a **local / single-operator grounded RAG demo**: trust boundaries around retrieved text are structural, errors are sanitized, CORS is explicit, connector tokens stay server-side, and the chat UI already projects citations and live updates. For that deployment mode the stack is coherent and reviewable.

It is **not** production-ready for multi-user workspaces: end-user authentication and complete workspace authorization remain open ([#182](https://github.com/mahmoudazaid/Kernector/issues/182), [#257](https://github.com/mahmoudazaid/Kernector/issues/257)), browser-local history is not a durable server transcript ([#288](https://github.com/mahmoudazaid/Kernector/issues/288)), regex input gates are defense-in-depth only ([#32](https://github.com/mahmoudazaid/Kernector/issues/32)), and cue-based `general_answer` routing still needs refinement ([#329](https://github.com/mahmoudazaid/Kernector/issues/329)). The highest-value *new* product gap from this review is citation navigation—users see provenance fields but cannot open a safe canonical source location ([#334](https://github.com/mahmoudazaid/Kernector/issues/334)).

---

## 3. Strengths (by area)

### Usability

- Grounded answers attach citations built 1:1 from retrieval hits ([`application/citations.py`](../application/citations.py)); chat renders source id, type, chunk index, and quote ([`ChatPanel.tsx`](../web/components/chat/ChatPanel.tsx) `CitationsBlock`).
- Conversation list + transcript persist in versioned `localStorage` with shape sanitization ([`conversations.ts`](../web/lib/session/conversations.ts), [`sanitize.ts`](../web/lib/chat/sanitize.ts)).
- Chat thread uses `aria-live="polite"` for assistant updates ([`ChatPanel.tsx`](../web/components/chat/ChatPanel.tsx)).
- Agent usage docs give a clear entry path and routing map ([`sprint-3-agent-usage.md`](sprint-3-agent-usage.md)).

### Security

- Retrieved context is delimited, defanged, and treated as untrusted data in the grounded system policy ([`grounded_rag_policy.py`](../application/grounded_rag_policy.py)); shared agent/eval markers live in [`untrusted_text.py`](../application/untrusted_text.py).
- Query reject patterns are explicitly documented as incomplete protection; reject messages never echo matched text ([`input_safety.py`](../application/input_safety.py)).
- HTTP failures map to RFC 9457 Problem Details without vendor bodies / prompts ([`errors.py`](../presentation/http/errors.py)).
- CORS allowlist is settings-driven and never `*`; empty when `HTTP_DEV_CORS` is off ([`app.py`](../presentation/http/app.py)).
- GitHub/Google OAuth stores grants on disk, redacts tokens in `repr`, uses single-use CSRF `state`, and avoids logging secrets ([`github/oauth.py`](../infrastructure/connectors/github/oauth.py), [`google_drive/oauth.py`](../infrastructure/connectors/google_drive/oauth.py)).

### Prompt engineering

- Platform grounded policy is a module constant; optional styles/task text compose and cannot replace it ([`grounded_rag_policy.py`](../application/grounded_rag_policy.py), [`response_style_policy.py`](../application/response_style_policy.py)).
- Style presets explicitly forbid changing grounding, citations, tools, or arguments.
- `TurnRouter` keeps allowlisted reason codes and does not auto-promote tools from raw affirmative history ([`turn_routing.py`](../application/turn_routing.py)).
- Insufficient-evidence paths can return a fixed answer without inventing from general knowledge (documented in ARCHITECTURE and grounded ask flow)—keeping honesty as a first-class product rule rather than model goodwill alone.

---

## 4. Findings

| ID | Area | Severity | Evidence | Impact | Recommended action | Tracking |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | Usability | Medium | `CitationResponse` has `source_id`, `source_type`, `quote`, `chunk_index` only ([`schemas.py`](../presentation/http/schemas.py)); UI shows plain text, no href ([`ChatPanel.tsx`](../web/components/chat/ChatPanel.tsx)); README notes citations are not page/section links | Users cannot verify or open the cited passage at a precise location | Add optional sanitized canonical URI / preview route / commit-pinned GitHub URL; keyboard-accessible open action | [#334](https://github.com/mahmoudazaid/Kernector/issues/334) |
| F2 | Usability | Medium | History under `kernector:conversations:v1` in `localStorage` ([`conversations.ts`](../web/lib/session/conversations.ts)) | Transcripts are device-local, lost on clear/another browser; no server audit trail | Server-side persistence | [#288](https://github.com/mahmoudazaid/Kernector/issues/288) |
| F3 | Security | High (prod multi-user) | No end-user session auth on chat/document APIs; workspace isolation incomplete per ARCHITECTURE / open epics | Any network client can hit the API as the operator; unsuitable for shared deployments | Ship authentication + workspace authorization | [#182](https://github.com/mahmoudazaid/Kernector/issues/182), [#257](https://github.com/mahmoudazaid/Kernector/issues/257) |
| F4 | Security / prompts | Medium | Regex/platform patterns in [`input_safety.py`](../application/input_safety.py); structural bounds elsewhere | Novel jailbreaks / multi-source injection can bypass matchers | Keep structural bounds primary; run adversarial experiment suite | [#32](https://github.com/mahmoudazaid/Kernector/issues/32) |
| F5 | Prompts / routing | Medium | `_GENERAL_CUES` / `_PROJECT_CUES` regex route to `general_answer` vs grounded ([`turn_routing.py`](../application/turn_routing.py)) | Mis-routes send project questions to ungrounded chat or over-block creative asks | Refine project-scoped general routing and out-of-scope handling | [#329](https://github.com/mahmoudazaid/Kernector/issues/329) |

---

## 5. Prioritized next actions

1. **Do not expand this ticket into feature work** — documentation + backlog only (#217).
2. **Keep [#182](https://github.com/mahmoudazaid/Kernector/issues/182) / [#257](https://github.com/mahmoudazaid/Kernector/issues/257)** as the production multi-user gate; treat current stack as single-operator until both close.
3. **Implement citation navigation (F1)** once tracked — highest usability win proportional to existing citation plumbing.
4. **Continue [#288](https://github.com/mahmoudazaid/Kernector/issues/288)** for durable history after auth exists (avoid storing sensitive transcripts only in the browser).
5. **Execute [#32](https://github.com/mahmoudazaid/Kernector/issues/32)** experiments; do not treat regex rejects as complete prompt-injection protection.
6. **Land [#329](https://github.com/mahmoudazaid/Kernector/issues/329)** so `general_answer` cues stay project-scoped and honest about out-of-scope asks.

---

## 6. Limitations

This artifact is a **static review** of repository files at the commit above. It did not include live adversarial prompting, browser accessibility audits with assistive tech, load/security scanning of a deployed instance, or a penetration test of OAuth/token storage. Severity for F3 is relative to **production multi-user** use; the same gaps are acceptable for local single-user demos documented in the README.
