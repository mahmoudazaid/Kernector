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
# Optional vault master key: docs/workspace-credential-vault.md

docker compose up -d --pull always
```

| Service | Host port (default) | Health |
| --- | --- | --- |
| UI (`web`) | 3000 | `GET /api/healthz` |
| API (`api`) | 8000 | `GET /health` |
| MCP (`mcp`) | 8100 | `GET /healthz` |
| `migrate` | (oneshot) | exits 0 before dependents start |

### First user (required to sign in)

Compose installs start with an empty auth database and no public sign-up.
Create the first local account **inside the API container**, then grant
workspace access:

```bash
docker compose exec api python -m presentation.cli.create_user --username alice
# prompts for password (no --password flag)

docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username alice --all-existing-projects
```

Open `http://localhost:3000` and sign in. MCP clients use
`http://127.0.0.1:8100/mcp` with a profile bearer from Admin → MCP Access.

**Do not** use host `uv run python -m presentation.cli.create_user` against a
Compose stack. That writes to the host path in `.env` (often
`data/auth/auth.sqlite`). Hub login uses the container volume at
`/data/auth/auth.sqlite` (`kernector-data`). A user that “already exists” on
the host is invisible to Compose until you create them with
`docker compose exec api …` as above.

Full how-to (more users, create projects, assign project grants):
[Users, projects, and grants (Docker Compose)](docker-users-and-projects.md).

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
| `/data/catalog/backups/` | Pre-migrate SQLite copies (only when a DB is behind shipped migrations; newest 5 per label retained, configurable via `migrate_sqlite --keep`) |

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

Pre-migrate SQLite copies also land under `/data/catalog/backups/` when a
database exists and still needs a shipped migration. Idempotent re-runs that
find every DB already current skip new backups. After a successful migrate,
only the newest five backups per label are kept (`--keep`, default `5`).

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
3. Find the bad release's migrate run time with
   `docker compose logs -t migrate`. Any
   `/data/catalog/backups/<label>-<UTC stamp>.sqlite` stamped at that run
   means it touched that database, **whether migrate succeeded or failed**
   (backups are written before applying; migrate may fail partway after
   earlier files or databases have already advanced). Only the newest five
   backups per label are kept after a *successful* run.
4. When that run wrote backups, restore those stamped files over each
   affected live database **before** pinning an older image. Delete that
   database's live `-wal` / `-shm` sidecars first so SQLite does not replay
   a stale WAL onto the restored file. The previous image's `migrate`
   refuses a schema ahead of what it ships (`unsupported schema version`),
   so pin-only rollback leaves API/MCP down when the bad release already
   moved schemas forward.
5. Then pin the previous known-good tag:
   `KERNECTOR_IMAGE_TAG=<previous> docker compose up -d`
6. Pin-only rollback is safe only when that run wrote no backups, meaning
   every database was already current or ahead (live files were left
   untouched). Failed migrate logs also include `backups=N`.
7. Restore from an external `tar` backup if the volume was damaged

## Local build (contributors)

GHCR `stable` may not publish every CPU architecture yet. On Apple Silicon,
`--pull always` can warn `no matching manifest for linux/arm64` and fall back
to a local build. `migrate` / `api` / `mcp` share one image tag; only `api`
declares `build` so Bake does not race three exports onto that tag.

```bash
docker compose build
docker compose up -d
```

Customers should prefer `--pull always` against GHCR tags rather than local
builds when an image exists for their platform.
