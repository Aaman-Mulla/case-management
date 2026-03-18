#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLASK_BIN="$PROJECT_DIR/venv/bin/flask"
APP_PATH="$PROJECT_DIR/run.py"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/var/backups}"
APP_CONFIG="${APP_CONFIG:-production}"

REQUIRED_VARS=(
  APP_CONFIG
  SECRET_KEY
  DATABASE_URL
  HOST
  PORT
  SERVER_MODE
)

errors=0
warnings=0

echo "== ROC Case Management Preflight =="
echo "Project: $PROJECT_DIR"
echo "Config: $APP_CONFIG"

if [[ ! -x "$FLASK_BIN" ]]; then
  echo "[FAIL] Flask binary missing at $FLASK_BIN"
  echo "       Create venv and install deps first."
  exit 1
fi

cd "$PROJECT_DIR"

for var_name in "${REQUIRED_VARS[@]}"; do
  value="${!var_name:-}"
  if [[ -z "$value" ]]; then
    echo "[FAIL] Required env var missing: $var_name"
    errors=$((errors + 1))
  else
    echo "[ OK ] $var_name is set"
  fi
done

if [[ "${APP_CONFIG:-}" != "production" ]]; then
  echo "[WARN] APP_CONFIG is not 'production'"
  warnings=$((warnings + 1))
fi

if [[ "${DATABASE_URL:-}" == sqlite://* ]]; then
  echo "[WARN] DATABASE_URL uses SQLite. PostgreSQL is recommended for production."
  warnings=$((warnings + 1))
fi

if [[ "${RATELIMIT_STORAGE_URI:-memory://}" == "memory://" ]]; then
  echo "[WARN] RATELIMIT_STORAGE_URI is memory:// (fine for single instance; use Redis for scaled deployment)."
  warnings=$((warnings + 1))
fi

mkdir -p "$BACKUP_DIR" || {
  echo "[FAIL] Cannot create backup directory: $BACKUP_DIR"
  errors=$((errors + 1))
}

if [[ -d "$BACKUP_DIR" ]]; then
  touch "$BACKUP_DIR/.preflight-write-test" 2>/dev/null || {
    echo "[FAIL] Backup directory not writable: $BACKUP_DIR"
    errors=$((errors + 1))
  }
  rm -f "$BACKUP_DIR/.preflight-write-test" 2>/dev/null || true
  echo "[ OK ] Backup directory writable: $BACKUP_DIR"
fi

echo "[....] Checking DB connectivity via flask db-status"
if APP_CONFIG="$APP_CONFIG" "$FLASK_BIN" --app "$APP_PATH" db-status >/tmp/case_mgmt_preflight_dbstatus.log 2>&1; then
  echo "[ OK ] Database connectivity check passed"
else
  echo "[FAIL] Database connectivity check failed"
  cat /tmp/case_mgmt_preflight_dbstatus.log
  errors=$((errors + 1))
fi

if [[ "$errors" -gt 0 ]]; then
  echo "\nPreflight result: FAILED ($errors errors, $warnings warnings)"
  exit 1
fi

echo "\nPreflight result: PASSED ($warnings warnings)"
exit 0
