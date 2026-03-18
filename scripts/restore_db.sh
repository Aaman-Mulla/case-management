#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLASK_BIN="$PROJECT_DIR/venv/bin/flask"
APP_PATH="$PROJECT_DIR/run.py"
APP_CONFIG="${APP_CONFIG:-production}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup-file>"
  exit 1
fi

INPUT_FILE="$1"

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "Backup file not found: $INPUT_FILE"
  exit 1
fi

if [[ ! -x "$FLASK_BIN" ]]; then
  echo "Flask binary not found at $FLASK_BIN"
  exit 1
fi

cd "$PROJECT_DIR"
APP_CONFIG="$APP_CONFIG" "$FLASK_BIN" --app "$APP_PATH" restore-db --input-file "$INPUT_FILE" --yes
