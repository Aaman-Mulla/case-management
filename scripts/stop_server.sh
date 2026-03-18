#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-5001}"
PID_FILE="$PROJECT_DIR/var/run/server.pid"
STOP_TIMEOUT="${STOP_TIMEOUT:-10}"

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi

  echo "Stopping process PID: $pid"
  kill "$pid" 2>/dev/null || true

  for _ in $(seq 1 "$STOP_TIMEOUT"); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "Graceful stop timed out. Forcing kill for PID: $pid"
  kill -9 "$pid" 2>/dev/null || true
  return 0
}

if [[ -f "$PID_FILE" ]]; then
  PID_FROM_FILE="$(cat "$PID_FILE" 2>/dev/null || true)"
  if stop_pid "$PID_FROM_FILE"; then
    rm -f "$PID_FILE"
    echo "Stopped"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -z "$PIDS" ]]; then
  echo "No listener found on port $PORT"
  exit 0
fi

echo "Stopping process(es) on port $PORT: $PIDS"
for pid in $PIDS; do
  stop_pid "$pid" || true
done

rm -f "$PID_FILE"
echo "Stopped"
