#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/deployment/runtime/run"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8501}"
status_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "$label: running (pid=$pid)"
    else
      echo "$label: stale pid file (pid=$pid)"
    fi
  else
    echo "$label: not started"
  fi
}
status_pid_file "$RUN_DIR/backend.pid" "backend"
status_pid_file "$RUN_DIR/frontend.pid" "frontend"
status_pid_file "$RUN_DIR/dashboard.pid" "dashboard"
echo "backend health:   http://127.0.0.1:${BACKEND_PORT}/health"
echo "frontend url:     http://127.0.0.1:${FRONTEND_PORT}"
echo "dashboard url:    http://127.0.0.1:${DASHBOARD_PORT}"
