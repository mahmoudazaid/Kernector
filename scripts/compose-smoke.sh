#!/usr/bin/env bash
# Fresh-install + upgrade smoke for Compose (#486).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT="kernector-smoke-$$"
TAG_A="${SMOKE_TAG_A:-smoke-a}"
TAG_B="${SMOKE_TAG_B:-smoke-b}"
ENV_FILE="${ROOT}/.tmp-compose-smoke.env"

cleanup() {
  docker compose -p "$PROJECT" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$ENV_FILE"
}
trap cleanup EXIT

cat >"$ENV_FILE" <<EOF
ADMIN_API_TOKEN=smoke-admin-token
AUTH_CSRF_KEY=smoke-csrf-key-change-me-32chars
DOCUMENT_CATALOG_WORKSPACE_ID=local
HTTP_DEV_CORS=true
HTTP_CORS_ORIGINS=http://localhost:3000
MCP_ALLOWED_HOSTS=127.0.0.1:8100,localhost:8100
AUTH_TRUSTED_ORIGINS=http://localhost:3000
EOF

if [[ "${SMOKE_SKIP_BUILD:-0}" != "1" ]]; then
  echo "==> Building images ($TAG_A)"
  docker build -f deploy/docker/Dockerfile.api -t "ghcr.io/mahmoudazaid/kernector-api:${TAG_A}" .
  docker build -f deploy/docker/Dockerfile.web -t "ghcr.io/mahmoudazaid/kernector-web:${TAG_A}" .
else
  echo "==> Using pre-pulled images ($TAG_A)"
fi

echo "==> Fresh install"
export KERNECTOR_IMAGE_TAG="$TAG_A"
docker compose -p "$PROJECT" --env-file "$ENV_FILE" up -d --pull missing
API_PORT="$(docker compose -p "$PROJECT" port api 8000 | awk -F: '{print $NF}')"
WEB_PORT="$(docker compose -p "$PROJECT" port web 3000 | awk -F: '{print $NF}')"
MCP_PORT="$(docker compose -p "$PROJECT" port mcp 8100 | awk -F: '{print $NF}')"

wait_http() {
  local url=$1
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "timeout waiting for $url" >&2
  docker compose -p "$PROJECT" ps
  docker compose -p "$PROJECT" logs
  return 1
}

wait_http "http://127.0.0.1:${API_PORT}/health"
wait_http "http://127.0.0.1:${WEB_PORT}/api/healthz"
wait_http "http://127.0.0.1:${MCP_PORT}/healthz"

echo "==> Seed local user + catalog marker"
# Seed only uses APIs available in TAG_A (may be previous :stable).
# Compose migrate already ran; do not import composition.sqlite_migrate here.
docker compose -p "$PROJECT" exec -T api \
  python - <<'PY'
from pathlib import Path
import sqlite3
from composition import load_runtime_settings
from composition.auth import create_local_user

settings = load_runtime_settings()
create_local_user("smoke-user", "smoke-password-ok")
catalog = settings.document_catalog.sql_path
assert catalog is not None
conn = sqlite3.connect(catalog)
conn.execute("CREATE TABLE IF NOT EXISTS smoke_marker (id INTEGER PRIMARY KEY, note TEXT)")
conn.execute("INSERT OR REPLACE INTO smoke_marker (id, note) VALUES (1, 'persist-me')")
conn.commit()
conn.close()
chroma = Path(settings.chroma.persist_path)
chroma.mkdir(parents=True, exist_ok=True)
(chroma / "smoke.txt").write_text("vector-ish", encoding="utf-8")
print("seeded")
PY

echo "==> Idempotent migrate on restart"
docker compose -p "$PROJECT" --env-file "$ENV_FILE" up -d --force-recreate migrate
docker compose -p "$PROJECT" --env-file "$ENV_FILE" up -d

if [[ "${SMOKE_SKIP_BUILD:-0}" != "1" && "$TAG_B" != "$TAG_A" ]]; then
  echo "==> Build upgrade images ($TAG_B)"
  docker build -f deploy/docker/Dockerfile.api -t "ghcr.io/mahmoudazaid/kernector-api:${TAG_B}" .
  docker build -f deploy/docker/Dockerfile.web -t "ghcr.io/mahmoudazaid/kernector-web:${TAG_B}" .
fi

echo "==> Upgrade / recreate with $TAG_B (reuse volumes)"
export KERNECTOR_IMAGE_TAG="$TAG_B"
docker compose -p "$PROJECT" --env-file "$ENV_FILE" up -d --pull missing --force-recreate
wait_http "http://127.0.0.1:${API_PORT}/health"
wait_http "http://127.0.0.1:${WEB_PORT}/api/healthz"
wait_http "http://127.0.0.1:${MCP_PORT}/healthz"

echo "==> Confirm persisted user/catalog/chroma"
docker compose -p "$PROJECT" exec -T api \
  python - <<'PY'
import sqlite3
from pathlib import Path
from composition import load_runtime_settings
from infrastructure.auth.sql_store import SqlAuthStore

settings = load_runtime_settings()
store = SqlAuthStore(settings.auth.sql_path)
user = store.get_user_by_username("smoke-user")
assert user is not None, "user missing after upgrade"
catalog = settings.document_catalog.sql_path
conn = sqlite3.connect(catalog)
row = conn.execute("SELECT note FROM smoke_marker WHERE id = 1").fetchone()
conn.close()
assert row == ("persist-me",), row
assert (Path(settings.chroma.persist_path) / "smoke.txt").read_text(encoding="utf-8") == "vector-ish"
print("persistence ok")
PY

echo "==> Migration failure blocks dependents and preserves data"
docker compose -p "$PROJECT" stop api mcp web
docker compose -p "$PROJECT" run --rm --no-deps \
  -e DOCUMENT_CATALOG_SQL_PATH=/data/catalog/catalog.sqlite \
  -e AUTH_SQL_PATH=/data/auth/auth.sqlite \
  api \
  python - <<'PY'
from pathlib import Path
from composition import load_runtime_settings

settings = load_runtime_settings()
path = settings.document_catalog.sql_path
assert path is not None
before = path.read_bytes()
Path("/tmp/before-bytes").write_bytes(before)
# Corrupt schema_version to an unsupported future version to force migrate failure.
import sqlite3
conn = sqlite3.connect(path)
conn.execute("UPDATE schema_version SET version = 999999")
conn.commit()
conn.close()
print("corrupted")
PY

set +e
docker compose -p "$PROJECT" run --rm --no-deps \
  -e DOCUMENT_CATALOG_SQL_PATH=/data/catalog/catalog.sqlite \
  -e AUTH_SQL_PATH=/data/auth/auth.sqlite \
  api python -m presentation.cli.migrate_sqlite
migrate_status=$?
set -e
if [[ "$migrate_status" -eq 0 ]]; then
  echo "expected migrate failure" >&2
  exit 1
fi

docker compose -p "$PROJECT" run --rm --no-deps \
  -e DOCUMENT_CATALOG_SQL_PATH=/data/catalog/catalog.sqlite \
  -e AUTH_SQL_PATH=/data/auth/auth.sqlite \
  api \
  python - <<'PY'
import sqlite3
from composition import load_runtime_settings
from infrastructure.auth.sql_store import SqlAuthStore

settings = load_runtime_settings()
path = settings.document_catalog.sql_path
assert path is not None
# Future-schema refusal writes nothing; live data must survive.
assert path.exists()
conn = sqlite3.connect(path)
row = conn.execute("SELECT note FROM smoke_marker WHERE id = 1").fetchone()
conn.close()
assert row == ("persist-me",), row
user = SqlAuthStore(settings.auth.sql_path).get_user_by_username("smoke-user")
assert user is not None, "user wiped after migrate refusal"
print("failure preserved live data")
PY

echo "compose smoke passed"
