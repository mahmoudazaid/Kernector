# Self-hosted Docker Compose (#486)

One-command local distribution for Kernector: API, Next.js UI, and MCP
Streamable HTTP, with SQLite + Chroma persistence on a named volume.

## Prerequisites

* Docker Desktop or Docker Engine with Compose v2
* Copy secrets into a customer-owned `.env` (never bake secrets into images)

## Installation

From a checkout that includes `compose.yaml` and `.env.example`:

```bash
cp .env.example .env
# Required for Admin MCP BFF / profiles:
#   ADMIN_API_TOKEN=...
#   AUTH_CSRF_KEY=...   # long random string
# Optional LLM keys as documented in .env.example

docker compose up -d --pull always
```

| Service | Host port (default) | Health |
| --- | --- | --- |
| UI (`web`) | 3000 | `GET /api/healthz` |
| API (`api`) | 8000 | `GET /health` |
| MCP (`mcp`) | 8100 | `GET /healthz` |
| `migrate` | (oneshot) | exits 0 before dependents start |

Open `http://localhost:3000`. MCP clients use `http://127.0.0.1:8100/mcp`
with a profile bearer from Admin → MCP Access.

## Initial configuration

Compose forces durable paths under the `kernector-data` volume (`/data` in
containers). Set secrets and optional providers in `.env` only:

* `ADMIN_API_TOKEN`, `AUTH_CSRF_KEY`, `AUTH_TRUSTED_ORIGINS`
* `DOCUMENT_CATALOG_WORKSPACE_ID` (default `local`)
* LLM / connector keys as needed
* `MCP_ALLOWED_HOSTS` for the MCP transport Host allowlist

Browser-facing API URL is baked into the web image as
`NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`). The web
container talks to the API on the Docker network via `API_BASE_URL=http://api:8000`.

## One-command update

```bash
docker compose up -d --pull always
```

This pulls the configured tag (`KERNECTOR_IMAGE_TAG`, default `stable`),
recreates changed containers, **reuses** `kernector-data`, and re-runs
`migrate` (idempotent). Ordinary pull/up never replaces existing SQLite or
Chroma files with empty seeds.

## Health and logs

```bash
docker compose ps
docker compose logs -f api web mcp migrate
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8100/healthz
curl -fsS http://127.0.0.1:3000/api/healthz
```

## Persistent paths

Named volume `kernector-data` → `/data`:

| Path | Contents |
| --- | --- |
| `/data/catalog/catalog.sqlite` | Document catalog, MCP profiles, artifacts, relationships |
| `/data/catalog/workspace_store.sqlite` | Versioned workspace records |
| `/data/catalog/response_feedback.sqlite` | Response feedback |
| `/data/auth/auth.sqlite` | Users, sessions, preferences, memberships |
| `/data/chroma` | Vector store |
| `/data/uploads` | Uploaded document blobs |
| `/data/knowledge` | Optional corpus file |
| `/data/*-oauth-*.json` / `jira-dc-*.json` | Connector grants/state when used |
| `/data/catalog/backups/` | Pre-migrate SQLite copies |

**Warning:** `docker compose down -v` removes `kernector-data` and deletes
local customer data.

## Backup and restore

While the stack is stopped (or at least idle):

```bash
docker compose stop
docker run --rm -v kernector-data:/data -v "$PWD/backup:/backup" \
  alpine tar czf /backup/kernector-data.tgz -C /data .
docker compose start
```

Restore into an empty volume, then `docker compose up -d`.

Pre-migrate SQLite copies also land under `/data/catalog/backups/` on each
migrate run when databases already exist.

## Version pinning

```bash
# Pin to an immutable release tag
KERNECTOR_IMAGE_TAG=0.1.0 docker compose up -d --pull always

# Track tested stable (default)
KERNECTOR_IMAGE_TAG=stable docker compose up -d --pull always
```

Images: `ghcr.io/mahmoudazaid/kernector-api` and
`ghcr.io/mahmoudazaid/kernector-web`. `stable` is promoted only after required
CI tests pass — not after every commit.

## Rollback / recovery

Automatic image rollback is **not** implemented. If a release is unhealthy:

1. Stop the stack: `docker compose stop`
2. Confirm volume intact: `docker volume inspect kernector-data`
3. Pin the previous known-good tag: `KERNECTOR_IMAGE_TAG=<previous> docker compose up -d`
4. If a migration failed, `migrate` exits non-zero and API/MCP do not start;
   original SQLite files remain, and a backup under `/data/catalog/backups/`
   can be copied back over the live `.sqlite` files if needed
5. Restore from an external `tar` backup if the volume was damaged

## Local build (contributors)

```bash
docker compose build
docker compose up -d
```

Customers should prefer `--pull always` against GHCR tags rather than local
builds.
