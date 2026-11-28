# Users, projects, and grants (Docker Compose)

Run every auth/project command **inside the API container**. Host
`uv run …` writes a different SQLite file than Hub login uses.

| Process | Auth DB |
| --- | --- |
| `docker compose exec api …` | `/data/auth/auth.sqlite` on volume `kernector-data` |
| Host `uv run …` | path from host `.env` (often `data/auth/auth.sqlite`) |

Workspace id is **not** created by CLI. It comes from
`DOCUMENT_CATALOG_WORKSPACE_ID` in `.env` (Compose default: `local`).

Prerequisites: stack up (`docker compose up -d`), from the repo root that
contains `compose.yaml`.

---

## 1. Create a user

No HTTP register. Password is prompted (no `--password` flag).

```bash
docker compose exec api python -m presentation.cli.create_user --username alice
```

Repeat for more accounts (e.g. `admin`, `member`).

---

## 2. Grant workspace membership

A user cannot use product APIs until they have membership in
`DOCUMENT_CATALOG_WORKSPACE_ID`.

**Empty catalog (no projects yet)** — membership only, so they can create
the first project after login:

```bash
docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username alice --all-existing-projects
```

**Grant every project that exists right now:**

```bash
docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username alice --all-existing-projects
```

**Grant specific projects** (ids look like `prj_…`):

```bash
docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username alice \
  --project-id prj_aaa \
  --project-id prj_bbb
```

Omitting both `--project-id` and `--all-existing-projects` is an error.
`--all-existing-projects` is a snapshot at grant time; new projects are not
auto-granted later.

---

## 3. Create a project

Projects are created over the Hub BFF after sign-in (creates self-grant the
project to the signed-in user).

```bash
# Sign in (cookie jar reused below)
COOKIE_JAR=$(mktemp)
curl -s -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -X POST http://localhost:3000/api/v1/auth/login \
  -H 'Content-Type: application/json' -H 'Origin: http://localhost:3000' \
  -d '{"username":"alice","password":"<password>"}'

# Create project — response includes project_id
curl -s -b "$COOKIE_JAR" -X POST http://localhost:3000/api/v1/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"Order Intake","slug":"order-intake"}'
```

Open `http://localhost:3000`, sign in, and use the same session in the UI
where project flows exist.

List projects:

```bash
curl -s -b "$COOKIE_JAR" http://localhost:3000/api/v1/projects
```

---

## 4. Assign users to projects

Grants are **explicit** per user. Membership alone does not open every
project.

Example: two projects; `admin` gets both; `member` gets only one.

```bash
# After you have project ids from create/list:
ADMIN_BOTH=(prj_alpha_id prj_beta_id)
MEMBER_ONE=prj_beta_id

docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username admin \
  --project-id "${ADMIN_BOTH[0]}" \
  --project-id "${ADMIN_BOTH[1]}"

docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username member \
  --project-id "$MEMBER_ONE"
```

Re-run `grant_workspace_access` when you add projects and need to extend a
user’s grants (`--all-existing-projects` or extra `--project-id` values).

---

## Typical first-boot sequence

```bash
docker compose up -d

docker compose exec api python -m presentation.cli.create_user --username admin
docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username admin --all-existing-projects

# Sign in at http://localhost:3000 as admin, create projects (UI or curl above),
# then grant other users:

docker compose exec api python -m presentation.cli.create_user --username member
docker compose exec api python -m presentation.cli.grant_workspace_access \
  --username member --project-id prj_…
```

See also [Self-hosted Docker Compose](self-hosted-docker.md).
