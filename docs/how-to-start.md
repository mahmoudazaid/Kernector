# How to start Kernector locally

For a one-command Docker install (API + UI + MCP), see
[self-hosted-docker.md](self-hosted-docker.md):

```bash
cp .env.example .env
docker compose up -d --pull always
```

Otherwise run each process in its **own terminal** from the **repository root**
(unless noted). Copy `.env.example` → `.env` and `web/.env.example` →
`web/.env.local` first if you have not already.

Required for the Next.js shell against local FastAPI:

```bash
# in repo-root .env
HTTP_DEV_CORS=true
HTTP_CORS_ORIGINS=http://localhost:3000
ADMIN_API_TOKEN=admin-dev-token   # MCP Admin UI / BFF (loaded into Next via next.config)
MCP_ALLOWED_HOSTS=127.0.0.1:8100,localhost:8100  # MCP transport only
```

`ADMIN_API_TOKEN` must match between FastAPI and the Next BFF. The web
`next.config` loads the repo-root `.env` so you do not need to duplicate it
into `web/.env.local` (you still can override there if you prefer).

Profile tokens and tool allowlists are **not** env vars — create them in
Admin UI [`/settings/mcp`](../web/app/settings/mcp/page.tsx).

---

## 1. Backend (FastAPI)

```bash
HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload
```

- URL: `http://127.0.0.1:8000`
- Health / settings: `curl -s http://127.0.0.1:8000/api/v1/settings | head`

---

## 2. Web (Next.js)

```bash
cd web
npm ci          # first time / after lockfile changes
npm run dev
```

- URL: `http://localhost:3000`
- Settings: `http://localhost:3000/settings`
- MCP Access: `http://localhost:3000/settings/mcp`

---

## 3. MCP (Streamable HTTP)

```bash
uv run uvicorn presentation.mcp.app:app --host 127.0.0.1 --port 8100
```

- Endpoint: `http://127.0.0.1:8100/mcp` (profile Bearer required)
- Health: `curl -s http://127.0.0.1:8100/healthz`

Create a token in **MCP Access**, then paste it into Cursor / Claude Code
`mcp.json`. Do not set `MCP_AUTH_TOKEN` / `MCP_TOOL_ALLOWLIST` (removed).

Optional reload during MCP work:

```bash
uv run uvicorn presentation.mcp.app:app --host 127.0.0.1 --port 8100 --reload
```

---

## Quick checklist

| Process | Port | Command |
| --- | --- | --- |
| Backend | 8000 | `HTTP_DEV_CORS=true uv run uvicorn presentation.http.app:app --reload` |
| Web | 3000 | `cd web && npm run dev` |
| MCP | 8100 | `uv run uvicorn presentation.mcp.app:app --host 127.0.0.1 --port 8100` |

More detail: [README — Local dual-stack](../README.md#local-dual-stack-fastapi--nextjs),
[README — MCP server](../README.md#run-the-mcp-streamable-http-server).
