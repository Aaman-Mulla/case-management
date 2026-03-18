#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLASK_BIN="$PROJECT_DIR/venv/bin/flask"
APP_PATH="$PROJECT_DIR/run.py"
OUTPUT_DIR="${1:-$PROJECT_DIR/var/backups}"
APP_CONFIG="${APP_CONFIG:-production}"

mkdir -p "$OUTPUT_DIR"

if [[ ! -x "$FLASK_BIN" ]]; then
  echo "Flask binary not found at $FLASK_BIN"
  exit 1
fi

cd "$PROJECT_DIR"
APP_CONFIG="$APP_CONFIG" "$FLASK_BIN" --app "$APP_PATH" backup-db --output-dir "$OUTPUT_DIR"
