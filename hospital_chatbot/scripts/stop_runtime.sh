#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/deployment/runtime/run"
QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=1
fi
stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      sleep 1
      kill -9 "$pid" >/dev/null 2>&1 || true
      [[ "$QUIET" -eq 1 ]] || echo "Stopped $label (pid=$pid)"
    fi
    rm -f "$pid_file"
  fi
}
stop_pid_file "$RUN_DIR/backend.pid" "backend"
stop_pid_file "$RUN_DIR/frontend.pid" "frontend"
stop_pid_file "$RUN_DIR/dashboard.pid" "dashboard"
