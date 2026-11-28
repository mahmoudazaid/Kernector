# ADR 0013: Local user authentication and preferences

## Status

Accepted

## Context

[#182](https://github.com/mahmoudazaid/Kernector/issues/182) requires
sign-in and at least one personalisation surface for Sprint 2, without
organisation RBAC. [#446](https://github.com/mahmoudazaid/Kernector/issues/446)
adds workspace membership and explicit project-grant persistence keyed by
that stable principal (`user_id`).

The Hub is Next.js talking to FastAPI over HTTP (ADR 0002). Runtime catalog
settings stay on `GET /api/v1/settings` (ADR 0005). Workspace identity remains
server-config only (ADR 0006). Trusted HTTP/MCP caller resolution and
authorization-before-retrieval remain [#447](https://github.com/mahmoudazaid/Kernector/issues/447).
Permission catalog and RBAC evaluation remain
[#456](https://github.com/mahmoudazaid/Kernector/issues/456).

## Decision

1. **Local username/password** — Accounts are provisioned only via CLI
   (`presentation.cli.create_user`): `--username` plus a hidden interactive
   password prompt. No HTTP register and no `--password` flag.

2. **Password hashing** — Stdlib `hashlib.scrypt` with explicit `maxmem`.
   Stored format: `scrypt$v1${n}${r}${p}${salt_b64url}${dk_b64url}` with
   `n=16384`, `r=8`, `p=1`, `dklen=64`, salt 16 bytes, `maxmem=32 MiB`.
   Unknown versions are rejected.

3. **SQLite sessions** — Opaque session ids hashed at rest (SHA-256). Cookie
   name `kernector_session` (`HttpOnly; SameSite=Lax; Path=/`; `Secure` when
   the browser-facing request is HTTPS). Successful login always issues a
   fresh session.

4. **Derived CSRF** — `HMAC-SHA256(AUTH_CSRF_KEY, session_id_plaintext)`,
   not stored in the database. `GET /me` returns the same value after reload
   without rotating the session. Required as `X-CSRF-Token` on logout and
   preference writes.

5. **Browser login gate** — `Content-Type: application/json` and exact
   `Origin` membership in `AUTH_TRUSTED_ORIGINS`. Cross-origin login is
   rejected. Generic failure messages; bounded failed attempts with lockout.

6. **Same-origin Next BFF** — Browser auth/preferences traffic goes through
   Next.js BFF routes that forward `Cookie` / `Set-Cookie` /
   `X-CSRF-Token`, preserve cookie attributes, set
   `Cache-Control: no-store`, and decide `Secure` from
   `x-forwarded-proto` or the request URL scheme. Direct browser→FastAPI
   cookie auth is unsupported; API CORS stays `allow_credentials=False`.
   Product `/api/v1/*` cookie forwarding for trusted callers is recorded in
   [ADR 0014](0014-trusted-workspace-context.md) Decision 8 (extends this
   auth/preferences-only scope from #182).

7. **Principal** — Frozen `Principal(user_id, username)`. `user_id` is
   immutable and stable across sessions for the same account (#446).

8. **Preferences** — `GET`/`PUT /api/v1/me/preferences` for preferred
   `provider` + `model`, validated against the runtime settings catalog.
   Missing preferences do not invent a row; stale pairs are returned with
   `usable: false` and chat falls back to catalog defaults. Generation
   knobs for signed-in users live in a per-user client key
   (`kernector:generation-settings:v1:<user_id>`); the anonymous
   `localStorage` provider/model pair is not written while signed in.

9. **Hub login gate** — The Next.js Hub requires a signed-in session for
   every product route. Unauthenticated browsers are redirected to
   `/login` (middleware cookie check plus client `AuthGate` after
   `GET /me`). The login surface uses Instrument panel chrome (ADR 0003):
   embossed fieldset, `.kern-settings-input`, primary `.kern-btn`, no
   workspace sidebar until authenticated.

10. **Workspace membership + project grants (#446)** — `auth.sqlite` stores
    `auth_workspace_memberships` (FK to `auth_users`) and
    `auth_project_grants` (FK to membership). Membership `role="member"` is
    an opaque assignment only; #446 does not evaluate permissions (#456).
    Active membership alone does **not** grant every project: each project
    needs an explicit active grant. `ProjectAccessPolicy`
    (`can_read` / `readable_projects`) is membership-and-grant-backed and
    default-deny. Composition exposes `build_project_access_policy`; HTTP/MCP
    product routes are not locked by this ADR (#447). No cross-database FK to
    catalog project tables; project existence is validated against the
    workspace-bound project store before granting.

11. **Operator bootstrap CLI (#446)** —
    `presentation.cli.grant_workspace_access` grants membership plus
    explicit `--project-id` values (repeatable) or
    `--all-existing-projects` (snapshot). Omitting both is an error, never
    “all projects”. Validation runs before any write so failures leave no
    partial membership/grant state. Single-host SQLite only; multi-instance
    persistence remains #271 / #270.

## Consequences

- `#446` owns membership and project-grant persistence; `#456` owns
  permission definitions and RBAC evaluation; `#447` owns trusted
  HTTP/MCP context application; `#457` consumes these stores for Super
  Admin membership administration.
- Secrets (passwords, session cookies, CSRF) must be redacted in FastAPI and
  BFF logs/error bodies. Authorization details must not leak through
  logs/errors.
- The auth SQLite file under `AUTH_SQL_PATH` (default `data/auth/`) is
  local-only runtime state — never commit it. `data/auth/` is gitignored.
- OpenAPI and `.env.example` document auth/preferences and auth env knobs.
- This ADR does not claim multi-instance readiness.

## Related docs

- [ADR 0002](0002-nextjs-presentation-migration.md)
- [ADR 0005](0005-consolidate-runtime-contract-on-settings.md)
- [ADR 0006](0006-workspace-scope-identity.md)
- [#182](https://github.com/mahmoudazaid/Kernector/issues/182)
- [#446](https://github.com/mahmoudazaid/Kernector/issues/446)
- [#447](https://github.com/mahmoudazaid/Kernector/issues/447) /
  [ADR 0014](0014-trusted-workspace-context.md) (trusted HTTP/MCP context)
- [#456](https://github.com/mahmoudazaid/Kernector/issues/456)
- [#457](https://github.com/mahmoudazaid/Kernector/issues/457)
