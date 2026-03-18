#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLASK_BIN="$PROJECT_DIR/venv/bin/flask"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
FLASK_APP_PATH="$PROJECT_DIR/run.py"
SERVE_APP_PATH="$PROJECT_DIR/serve.py"

RUN_DIR="$PROJECT_DIR/var/run"
LOG_DIR="$PROJECT_DIR/var/log"
PID_FILE="$RUN_DIR/server.pid"
LOG_FILE="${LOG_FILE:-$LOG_DIR/server.log}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5001}"
APP_CONFIG="${APP_CONFIG:-development}"
SERVER_MODE="${SERVER_MODE:-flask}"

if [[ ! -x "$FLASK_BIN" ]]; then
  echo "Flask binary not found at $FLASK_BIN"
  echo "Create the virtual environment first: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Server already running (PID: $EXISTING_PID)."
    echo "Use ./scripts/stop_server.sh first, or check $LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use by another process."
  echo "Stop that process or use a different PORT before starting."
  exit 1
fi

if [[ "$SERVER_MODE" == "waitress" ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python binary not found at $PYTHON_BIN"
    exit 1
  fi
  START_CMD=("$PYTHON_BIN" "$SERVE_APP_PATH")
else
  START_CMD=("$FLASK_BIN" --app "$FLASK_APP_PATH" run --host "$HOST" --port "$PORT" --no-reload)
fi

echo "Starting ROC Case Management on http://$HOST:$PORT"
echo "Mode: $SERVER_MODE | Config: $APP_CONFIG | Log: $LOG_FILE"

APP_CONFIG="$APP_CONFIG" HOST="$HOST" PORT="$PORT" nohup "${START_CMD[@]}" >>"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 1
if ! kill -0 "$NEW_PID" 2>/dev/null; then
  echo "Failed to start server. Check logs: $LOG_FILE"
  rm -f "$PID_FILE"
  exit 1
fi

echo "Started (PID: $NEW_PID)"
