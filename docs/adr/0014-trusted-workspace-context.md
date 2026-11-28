# ADR 0014: Trusted workspace resolution and authorization ordering

## Status

Accepted

## Context

[#447](https://github.com/mahmoudazaid/Kernector/issues/447) requires that
HTTP and MCP product paths derive the active workspace from an authenticated
principal and verified membership, and that authorization runs before catalog,
retrieval, provider, or mutation work.

[ADR 0006](0006-workspace-scope-identity.md) established `workspace_id` as
scope identity and historically treated
`DOCUMENT_CATALOG_WORKSPACE_ID` as the sole live workspace source for product
behavior. Membership persistence and `ProjectAccessPolicy` are delivered by
[#446](https://github.com/mahmoudazaid/Kernector/issues/446) and documented in
[ADR 0013](0013-local-user-auth-and-preferences.md) (accepted; this ADR does
not rewrite 0013’s decision text).

Physical vector/lexical isolation remains
[#448](https://github.com/mahmoudazaid/Kernector/issues/448). Action-level RBAC
remains [#456](https://github.com/mahmoudazaid/Kernector/issues/456).

## Decision

1. **Trusted HTTP workspace selection** — The active workspace for product
   HTTP requests is server-owned and derived from the authenticated principal
   and active memberships:
   - zero active memberships → deny (403 once authenticated)
   - one → auto-select
   - multiple → prefer a membership-validated server-side session selection;
     until [#448](https://github.com/mahmoudazaid/Kernector/issues/448), if
     there is no session selection, auto-select the process-bound
     `DOCUMENT_CATALOG_WORKSPACE_ID` when it is among the caller's active
     memberships; otherwise require session selection (never trust a raw
     client `workspace_id` as authorization)

2. **Bootstrap mode** — `DOCUMENT_CATALOG_WORKSPACE_ID` is only an explicit
   single-operator bootstrap constraint when `AUTH_WORKSPACE_BOOTSTRAP` is
   enabled. Bootstrap still requires active membership in that workspace. There
   is no implicit `"default"` workspace. Until #448, non-bootstrap HTTP also
   prefers that process-bound id among multiple memberships (Decision 1).

3. **Seam contract** — Composition resolves
   `ProjectAccessCaller(principal, workspace_id)` from an authenticated
   `Principal`, an already-trusted server-selected `workspace_id`, and
   `MembershipStore`. Env/`_require_workspace_id` is not the universal HTTP
   product resolver.

4. **Authorization ordering** —
   `Principal → trusted selection → membership verification → ProjectAccessCaller → ProjectAccessPolicy → work`.
   Catalog, vector, OAuth stores, provider clients, and use-case factories must
   not run before authorization. OAuth start binds state to `user_id` + trusted
   `workspace_id`; callback validates that binding before token exchange.

5. **Status codes** — 401 missing authentication; 403 authenticated
   workspace-level denial without resource probing; sanitized 404 for
   client-addressable foreign workspace/project identifiers.

6. **`ProjectAccessPolicy.can_read`** — Project-scope isolation gate for
   reads/mutations under #447, not write/action permission (#456).

7. **MCP** — Access profiles bind a required acting `user_id` (legacy null
   rows fail closed at auth; new profiles must assign non-null). Auth order:
   bearer profile → principal lookup → membership → `ProjectAccessCaller` →
   project policy → tool dispatch. `McpCallerContext` is constructed from the
   resolved `ProjectAccessCaller`, profile project, and allowlist.

8. **Same-origin product BFF** — Extends [ADR 0013](0013-local-user-auth-and-preferences.md)
   Decision 6: Hub browser traffic for product `/api/v1/*` (documents, chat,
   connectors, OAuth start/callback, projects, etc.) also goes through the
   Next.js same-origin BFF with `Cookie` / `Set-Cookie` / `X-CSRF-Token`
   forwarding (`proxyAuthApi` + catch-all). Provider OAuth redirect URIs must
   target the Hub origin (not FastAPI `:8000`) so the top-level callback GET
   carries `kernector_session` (`SameSite=Lax`). Direct browser→FastAPI cookie
   auth remains unsupported; API CORS stays `allow_credentials=False`.

## Consequences

- ADR 0006 Decision 2’s live product meaning (env as sole workspace source for
  product requests) is superseded here; catalog construction may still bind one
  process workspace from env until #448.
- #447 unblocks per-workspace OAuth grant stores (#269, #449) and retrieval
  isolation (#448) that need trusted workspace binding input.
- Operators recreate or rebind legacy MCP profiles that lack `user_id`.
- Operators re-register Google/GitHub/Atlassian OAuth redirect URIs to the Hub
  origin when upgrading from FastAPI-direct callbacks.

## Related docs

- [ADR 0006](0006-workspace-scope-identity.md)
- [ADR 0013](0013-local-user-auth-and-preferences.md)
- [#446](https://github.com/mahmoudazaid/Kernector/issues/446)
- [#447](https://github.com/mahmoudazaid/Kernector/issues/447)
- [#269](https://github.com/mahmoudazaid/Kernector/issues/269)
- [#449](https://github.com/mahmoudazaid/Kernector/issues/449)
