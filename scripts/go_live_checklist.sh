#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLASK_BIN="$PROJECT_DIR/venv/bin/flask"
APP_PATH="$PROJECT_DIR/run.py"

APP_CONFIG="${APP_CONFIG:-production}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/var/backups}"
MIGRATION_SQL_OUT="${MIGRATION_SQL_OUT:-$PROJECT_DIR/var/log/migration-preview.sql}"

mkdir -p "$BACKUP_DIR" "$(dirname "$MIGRATION_SQL_OUT")"

if [[ ! -x "$FLASK_BIN" ]]; then
  echo "[FAIL] Flask binary not found at $FLASK_BIN"
  exit 1
fi

cd "$PROJECT_DIR"

echo "== Go-Live Checklist =="
echo "Project: $PROJECT_DIR"
echo "Config: $APP_CONFIG"

echo "\n[1/3] Running preflight checks"
APP_CONFIG="$APP_CONFIG" BACKUP_DIR="$BACKUP_DIR" "$PROJECT_DIR/scripts/preflight_check.sh"

echo "\n[2/3] Creating backup"
APP_CONFIG="$APP_CONFIG" "$FLASK_BIN" --app "$APP_PATH" backup-db --output-dir "$BACKUP_DIR"

echo "\n[3/3] Checking migrations (dry-run SQL generation)"
APP_CONFIG="$APP_CONFIG" "$FLASK_BIN" --app "$APP_PATH" db upgrade --sql > "$MIGRATION_SQL_OUT"

if [[ ! -s "$MIGRATION_SQL_OUT" ]]; then
  echo "[WARN] Migration SQL preview file is empty: $MIGRATION_SQL_OUT"
else
  echo "[ OK ] Migration preview written: $MIGRATION_SQL_OUT"
fi

echo "\nGo-live checklist PASSED"
echo "- Backup dir: $BACKUP_DIR"
echo "- Migration preview: $MIGRATION_SQL_OUT"
