# Capstone demo: Issue → Test Design (local)

> **This is a local, reproducible demo. There is no hosted URL.** Kernector
> needs server-side provider credentials and a GitHub OAuth grant, so
> the "demo link" is this runbook plus a dated verification note at the end.

Two paths reach the same Test Design workflow:

- **Path A: Next.js.** Chat → Start Test Design → Test selection → Test steps.
  Needs GitHub connected in Knowledge Hub.
- **Path B: MCP.** A coding assistant (Cursor, Claude Code) fetches the Issue
  itself and calls `test_design_start_from_text`. No GitHub connection is
  needed in Kernector.

## Setup

Use the repository [README](../../README.md) as the setup source of truth
(canonical operator guide: [#105](https://github.com/mahmoudazaid/Kernector/issues/105)).
Relevant sections:

- [Next.js + FastAPI local workflow](../../README.md#nextjs--fastapi-local-workflow)
- [Sync documents from GitHub → Knowledge Hub (user OAuth)](../../README.md#knowledge-hub-user-oauth-1)
- [Run the MCP Streamable HTTP server](../../README.md#run-the-mcp-streamable-http-server)
- [Troubleshooting](../../README.md#troubleshooting)

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22 (`web/.nvmrc`), npm,
and an LLM provider key (OpenRouter) or a local Ollama model.

### Capstone-specific configuration

Copy [`.env.example`](../../.env.example) to `.env` and set:

```bash
HTTP_DEV_CORS=true
DOCUMENT_CATALOG_WORKSPACE_ID=local
DOMAIN_TOOL_PACKS=software-delivery      # enables Test Design
OPENROUTER_API_KEY=<your key>            # or LLM_PROVIDER=ollama + OLLAMA_* values
```

Path A also needs a GitHub OAuth App (see the README GitHub section):

```bash
GITHUB_OAUTH_CLIENT_ID=<client id>
GITHUB_OAUTH_CLIENT_SECRET=<client secret>
GITHUB_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/v1/connectors/github/oauth/callback
GITHUB_OAUTH_FRONTEND_REDIRECT=http://localhost:3000/documents
```

Never commit `.env`. Install dependencies:

```bash
uv sync --extra github
cd web && npm ci
```

## Start the servers

Each process runs in its own terminal. Path A needs terminals 1 and 2. Path B
needs terminal 3 only. All three can run at the same time.

| Terminal | Process | URL | Used by |
| --- | --- | --- | --- |
| 1 | FastAPI (API for the web app) | `http://127.0.0.1:8000` | Path A |
| 2 | Next.js web app | `http://localhost:3000` | Path A |
| 3 | MCP server | `http://127.0.0.1:8100/mcp` | Path B |

**Terminal 1: API for the web app.** Start it before the web app. Run it from
the repository root:

```bash
HTTP_DEV_CORS=true DOMAIN_TOOL_PACKS=software-delivery \
  uv run uvicorn presentation.http.app:app --reload
```

**Terminal 2: web app.**

```bash
cd web
npm run dev
```

**Terminal 3: MCP server.** Run it from the repository root:

```bash
export MCP_AUTH_TOKEN=dev-token
export MCP_ALLOWED_HOSTS=127.0.0.1:8100
export MCP_TOOL_ALLOWLIST=software_delivery.test_design_start_from_text,software_delivery.test_design_get,software_delivery.test_design_confirm,software_delivery.test_design_generate,software_delivery.test_design_export_feature
export DOMAIN_TOOL_PACKS=software-delivery
export DOCUMENT_CATALOG_WORKSPACE_ID=local
uv run uvicorn presentation.mcp.app:app --host 127.0.0.1 --port 8100
```

Health checks:

```bash
curl -s http://127.0.0.1:8000/health      # API: {"status":"ok"}
curl -s http://127.0.0.1:8100/healthz     # MCP: {"status":"ok"}
```

Values set in `.env` also apply, so the inline variables above can be dropped
once they are in `.env`. Process environment wins over `.env`.

## Path A: Next.js

1. Start terminals 1 and 2 from [Start the servers](#start-the-servers).
2. Check `GET http://127.0.0.1:8000/health`, and that
   `GET http://127.0.0.1:8000/api/v1/settings` returns `software-delivery` in
   `enabled_packs`.
3. Open `/documents` (Knowledge Hub), click **Connect** on the GitHub card, and
   complete consent. Test Design reads the Issue live through this grant. A
   public Issue still needs the connection
   ([#302](https://github.com/mahmoudazaid/Kernector/issues/302)).
4. Open `/chat` and send, for example:

   ```text
   design tests https://github.com/<owner>/<repo>/issues/<number>
   ```

   Exactly one Issue locator makes the request ready. The reply carries a
   **Start Test Design** action.
5. Click **Start Test Design**. Kernector fetches the Issue, suggests coverage
   candidates, and opens `/test-design/<draftId>`.
6. **Test selection:** keep or drop candidates, add your own, and choose
   **Manual** or **Cucumber** per candidate. Click **Next**.
7. **Test steps:** Kernector generates grounded cases. Manual cases have
   preconditions, steps, and an expected result. Cucumber cases share one
   Feature and Background. Edit a case; the status shows **Saved** after
   autosave.
8. Optional: edit the Issue on GitHub, then regenerate. Kernector re-fetches
   the Issue and refuses to write when the evidence changed.

Optional exports (Google Drive, Xray) are outside the Capstone path.

## Path B: MCP (no GitHub connection in Kernector)

1. Start terminal 3 (MCP server) from [Start the servers](#start-the-servers).
2. Add the `kernector` server to Cursor's `mcp.json` (fragment in the
   [README](../../README.md#run-the-mcp-streamable-http-server)).
3. Ask the assistant to fetch an Issue with its own tools (`gh`, GitHub MCP)
   and design tests for it. The assistant calls
   `test_design_start_from_text` → `test_design_confirm` →
   `test_design_generate`, and optionally `test_design_export_feature` for a
   `.feature` file.
4. Results report `evidence_origin: client_supplied`: Kernector did not verify
   the text against a live source.

Arguments, errors, and the `untrusted_model_output` marker:
[pack README § Test Design over MCP](../../packs/software_delivery/README.md#test-design-over-mcp-338).

## Verification note

Fill in after each verified run and link the latest note from the
[evidence tracker](README.md#evidence-tracker).

| Field | Value |
| --- | --- |
| Date | |
| Commit SHA | |
| Path (A / B) | |
| LLM provider / model | |
| Issue used | |
| Draft started (draft id) | |
| Candidates suggested / kept | |
| Cases generated (manual / Cucumber) | |
| Edit saved | |
| Problems seen | |
