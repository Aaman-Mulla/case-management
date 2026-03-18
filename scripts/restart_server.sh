#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5001}"
HEALTH_PATH="${HEALTH_PATH:-/auth/login}"

"$PROJECT_DIR/scripts/stop_server.sh"
"$PROJECT_DIR/scripts/start_server.sh"

sleep 1
STATUS_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST:$PORT$HEALTH_PATH" || true)"
echo "Health check $HEALTH_PATH -> ${STATUS_CODE:-000}"
