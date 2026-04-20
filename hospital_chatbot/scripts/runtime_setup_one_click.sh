#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/deployment/runtime/logs"
RUN_DIR="$PROJECT_ROOT/deployment/runtime/run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
PIP_BIN="${PIP_BIN:-pip}"
NPM_BIN="${NPM_BIN:-npm}"
STREAMLIT_BIN="${STREAMLIT_BIN:-streamlit}"

WORKBOOK_PATH="${WORKBOOK_PATH:-$PROJECT_ROOT/data/master_kb.xlsx}"
KNOWLEDGE_JSONL="${KNOWLEDGE_JSONL:-$PROJECT_ROOT/data/knowledge.jsonl}"
KNOWLEDGE_CSV="${KNOWLEDGE_CSV:-$PROJECT_ROOT/data/knowledge.csv}"
VALIDATION_REPORT="${VALIDATION_REPORT:-$PROJECT_ROOT/data/kb_validation_report.json}"
KB_MANIFEST="${KB_MANIFEST:-$PROJECT_ROOT/data/kb_manifest.json}"
TEST_SET="${TEST_SET:-$PROJECT_ROOT/data/regression_test_set_realistic.jsonl}"
EVAL_REPORT="${EVAL_REPORT:-$PROJECT_ROOT/data/evaluation_report.json}"
EVAL_DETAILS="${EVAL_DETAILS:-$PROJECT_ROOT/data/evaluation_details.jsonl}"
CHROMA_DB_DIR="${CHROMA_DB_DIR:-$PROJECT_ROOT/chroma_db}"
CHROMA_COLLECTION="${CHROMA_COLLECTION:-hospital_faq}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_MODE="${FRONTEND_MODE:-nextjs}"   # nextjs | static | none
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
START_DASHBOARD=0
DASHBOARD_PORT="${DASHBOARD_PORT:-8501}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"
INSTALL_FRONTEND_DEPS=1
SKIP_INSTALL=0
SKIP_BUILD=0
SKIP_REINDEX=0
SKIP_TESTSET=0
SKIP_EVAL=0
SKIP_BACKEND=0
SKIP_FRONTEND=0
SKIP_HEALTHCHECK=0
NO_START=0
RESET_INDEX=1
DRY_RUN=0

usage() {
  cat <<USAGE
Usage: bash scripts/runtime_setup_one_click.sh [options]

Options:
  --workbook PATH           Path to master Excel workbook
  --frontend-mode MODE      nextjs | static | none
  --backend-port PORT       Backend port (default: 8000)
  --frontend-port PORT      Frontend port for Next.js (default: 3000)
  --dashboard-port PORT     Dashboard port (default: 8501)
  --start-dashboard         Start Streamlit dashboard after setup
  --skip-install            Skip pip install -r requirements.txt
  --skip-build              Skip build_kb.py
  --skip-reindex            Skip reindex_kb.py
  --skip-testset            Skip generate_test_set.py
  --skip-eval               Skip evaluate.py
  --skip-backend            Do not start backend
  --skip-frontend           Do not start frontend
  --no-start                Run setup only; do not start services
  --skip-healthcheck        Do not wait for service health checks
  --skip-frontend-install   Skip npm install in nextjs_frontend
  --skip-reset-index        Reindex without --reset
  --dry-run                 Print commands only
  -h, --help                Show this help
USAGE
}

log() {
  printf '[runtime-setup] %s\n' "$*"
}

die() {
  printf '[runtime-setup][ERROR] %s\n' "$*" >&2
  exit 1
}

run_cmd() {
  log "$*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

run_shell() {
  log "$*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    bash -lc "$*"
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

wait_http_ok() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"
  local sleep_s="${4:-1}"
  if [[ "$DRY_RUN" -eq 1 || "$SKIP_HEALTHCHECK" -eq 1 ]]; then
    return 0
  fi
  for ((i=1; i<=attempts; i++)); do
    if "$PYTHON_BIN" - "$url" <<'PY' >/dev/null 2>&1
import sys, urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2) as resp:
        raise SystemExit(0 if 200 <= resp.status < 500 else 1)
except Exception:
    raise SystemExit(1)
PY
    then
      log "$label พร้อมใช้งานที่ $url"
      return 0
    fi
    sleep "$sleep_s"
  done
  die "$label ไม่พร้อมภายในเวลาที่กำหนด: $url"
}

write_pid() {
  local pid_file="$1"
  local pid="$2"
  mkdir -p "$(dirname "$pid_file")"
  printf '%s\n' "$pid" > "$pid_file"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workbook) WORKBOOK_PATH="$2"; shift 2 ;;
    --frontend-mode) FRONTEND_MODE="$2"; shift 2 ;;
    --backend-port) BACKEND_PORT="$2"; API_BASE_URL="http://127.0.0.1:${BACKEND_PORT}"; shift 2 ;;
    --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
    --dashboard-port) DASHBOARD_PORT="$2"; shift 2 ;;
    --start-dashboard) START_DASHBOARD=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-reindex) SKIP_REINDEX=1; shift ;;
    --skip-testset) SKIP_TESTSET=1; shift ;;
    --skip-eval) SKIP_EVAL=1; shift ;;
    --skip-backend) SKIP_BACKEND=1; shift ;;
    --skip-frontend) SKIP_FRONTEND=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --skip-healthcheck) SKIP_HEALTHCHECK=1; shift ;;
    --skip-frontend-install) INSTALL_FRONTEND_DEPS=0; shift ;;
    --skip-reset-index) RESET_INDEX=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -f "$PROJECT_ROOT/requirements.txt" ]] || die "requirements.txt not found in $PROJECT_ROOT"
[[ -f "$WORKBOOK_PATH" ]] || die "Workbook not found: $WORKBOOK_PATH"
[[ "$FRONTEND_MODE" =~ ^(nextjs|static|none)$ ]] || die "Invalid --frontend-mode: $FRONTEND_MODE"

need_cmd "$PYTHON_BIN"
need_cmd "$PIP_BIN"
if [[ "$FRONTEND_MODE" == "nextjs" && "$SKIP_FRONTEND" -eq 0 && "$NO_START" -eq 0 ]]; then
  need_cmd "$NPM_BIN"
fi
if [[ "$START_DASHBOARD" -eq 1 && "$NO_START" -eq 0 ]]; then
  need_cmd "$STREAMLIT_BIN"
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SETUP_LOG="$LOG_DIR/runtime_setup_${TIMESTAMP}.log"
BACKEND_LOG="$LOG_DIR/backend_${TIMESTAMP}.log"
FRONTEND_LOG="$LOG_DIR/frontend_${TIMESTAMP}.log"
DASHBOARD_LOG="$LOG_DIR/dashboard_${TIMESTAMP}.log"

exec > >(tee -a "$SETUP_LOG") 2>&1

log "PROJECT_ROOT=$PROJECT_ROOT"
log "WORKBOOK_PATH=$WORKBOOK_PATH"
log "FRONTEND_MODE=$FRONTEND_MODE"
log "BACKEND_PORT=$BACKEND_PORT FRONTEND_PORT=$FRONTEND_PORT DASHBOARD_PORT=$DASHBOARD_PORT"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  run_cmd "$PIP_BIN" install -r "$PROJECT_ROOT/requirements.txt"
else
  log "ข้าม pip install ตามที่ร้องขอ"
fi

if [[ "$FRONTEND_MODE" == "nextjs" && "$INSTALL_FRONTEND_DEPS" -eq 1 ]]; then
  if [[ -f "$PROJECT_ROOT/nextjs_frontend/package.json" ]]; then
    run_shell "cd '$PROJECT_ROOT/nextjs_frontend' && '$NPM_BIN' install"
  else
    die "nextjs_frontend/package.json not found"
  fi
fi

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  run_cmd "$PYTHON_BIN" "$PROJECT_ROOT/scripts/build_kb.py" \
    --input "$WORKBOOK_PATH" \
    --jsonl-output "$KNOWLEDGE_JSONL" \
    --csv-output "$KNOWLEDGE_CSV" \
    --report-output "$VALIDATION_REPORT" \
    --manifest-output "$KB_MANIFEST"
else
  log "ข้าม build_kb.py ตามที่ร้องขอ"
fi

if [[ "$SKIP_REINDEX" -eq 0 ]]; then
  REINDEX_CMD=("$PYTHON_BIN" "$PROJECT_ROOT/scripts/reindex_kb.py" --knowledge "$KNOWLEDGE_JSONL" --db-dir "$CHROMA_DB_DIR" --collection "$CHROMA_COLLECTION")
  if [[ "$RESET_INDEX" -eq 1 ]]; then
    REINDEX_CMD+=(--reset)
  fi
  run_cmd "${REINDEX_CMD[@]}"
else
  log "ข้าม reindex_kb.py ตามที่ร้องขอ"
fi

if [[ "$SKIP_TESTSET" -eq 0 ]]; then
  run_cmd "$PYTHON_BIN" "$PROJECT_ROOT/scripts/generate_test_set.py" --knowledge "$KNOWLEDGE_JSONL" --output "$TEST_SET"
else
  log "ข้าม generate_test_set.py ตามที่ร้องขอ"
fi

if [[ "$SKIP_EVAL" -eq 0 ]]; then
  run_cmd "$PYTHON_BIN" "$PROJECT_ROOT/scripts/evaluate.py" \
    --test-set "$TEST_SET" \
    --report-output "$EVAL_REPORT" \
    --details-output "$EVAL_DETAILS" \
    --manifest "$KB_MANIFEST"
else
  log "ข้าม evaluate.py ตามที่ร้องขอ"
fi

# stop previous services if pid files exist
if [[ "$NO_START" -eq 0 ]]; then
  if [[ -x "$PROJECT_ROOT/scripts/stop_runtime.sh" ]]; then
    run_cmd "$PROJECT_ROOT/scripts/stop_runtime.sh" --quiet || true
  fi
fi

if [[ "$NO_START" -eq 0 && "$SKIP_BACKEND" -eq 0 ]]; then
  log "เริ่ม backend..."
  if [[ "$DRY_RUN" -eq 0 ]]; then
    nohup env \
      PYTHONPATH="$PROJECT_ROOT" \
      WORKBOOK_PATH="$WORKBOOK_PATH" \
      KNOWLEDGE_JSONL="$KNOWLEDGE_JSONL" \
      KNOWLEDGE_CSV="$KNOWLEDGE_CSV" \
      VALIDATION_REPORT_PATH="$VALIDATION_REPORT" \
      MANIFEST_PATH="$KB_MANIFEST" \
      EVAL_REPORT_PATH="$EVAL_REPORT" \
      CHROMA_DB_DIR="$CHROMA_DB_DIR" \
      CHROMA_COLLECTION="$CHROMA_COLLECTION" \
      "$PYTHON_BIN" -m uvicorn backend.app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" > "$BACKEND_LOG" 2>&1 &
    BACKEND_PID=$!
    write_pid "$RUN_DIR/backend.pid" "$BACKEND_PID"
  fi
  wait_http_ok "http://127.0.0.1:${BACKEND_PORT}/health" "Backend"
fi

if [[ "$NO_START" -eq 0 && "$SKIP_FRONTEND" -eq 0 ]]; then
  case "$FRONTEND_MODE" in
    nextjs)
      log "เริ่ม Next.js frontend..."
      if [[ "$DRY_RUN" -eq 0 ]]; then
        nohup env NEXT_PUBLIC_API_BASE_URL="$API_BASE_URL" \
          bash -lc "cd '$PROJECT_ROOT/nextjs_frontend' && '$NPM_BIN' run dev -- --hostname '$FRONTEND_HOST' --port '$FRONTEND_PORT'" > "$FRONTEND_LOG" 2>&1 &
        FRONTEND_PID=$!
        write_pid "$RUN_DIR/frontend.pid" "$FRONTEND_PID"
      fi
      wait_http_ok "http://127.0.0.1:${FRONTEND_PORT}" "Next.js Frontend"
      ;;
    static)
      log "ใช้ static frontend ผ่าน backend ที่ / และ /admin-ui"
      ;;
    none)
      log "ไม่เริ่ม frontend ตามโหมด none"
      ;;
  esac
fi

if [[ "$NO_START" -eq 0 && "$START_DASHBOARD" -eq 1 ]]; then
  log "เริ่ม Streamlit dashboard..."
  if [[ "$DRY_RUN" -eq 0 ]]; then
    nohup env PYTHONPATH="$PROJECT_ROOT" \
      "$STREAMLIT_BIN" run "$PROJECT_ROOT/dashboard/dashboard_app.py" --server.port "$DASHBOARD_PORT" --server.address 0.0.0.0 > "$DASHBOARD_LOG" 2>&1 &
    DASHBOARD_PID=$!
    write_pid "$RUN_DIR/dashboard.pid" "$DASHBOARD_PID"
  fi
  wait_http_ok "http://127.0.0.1:${DASHBOARD_PORT}" "Dashboard"
fi

cat <<SUMMARY

==================== Runtime Setup Summary ====================
Workbook:        $WORKBOOK_PATH
Knowledge JSONL: $KNOWLEDGE_JSONL
Manifest:        $KB_MANIFEST
Test set:        $TEST_SET
Eval report:     $EVAL_REPORT
Setup log:       $SETUP_LOG
Backend log:     $BACKEND_LOG
Frontend log:    $FRONTEND_LOG
Dashboard log:   $DASHBOARD_LOG
Backend URL:     http://127.0.0.1:${BACKEND_PORT}
Frontend URL:    $( [[ "$FRONTEND_MODE" == "nextjs" ]] && echo "http://127.0.0.1:${FRONTEND_PORT}" || echo "served by backend or disabled" )
Guide API:       http://127.0.0.1:${BACKEND_PORT}/guide
Admin UI:        http://127.0.0.1:${BACKEND_PORT}/admin-ui
Status API:      http://127.0.0.1:${BACKEND_PORT}/admin/status
===============================================================
SUMMARY
