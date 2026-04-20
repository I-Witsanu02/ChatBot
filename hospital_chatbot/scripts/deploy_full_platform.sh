#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/deployment/full/logs"
RELEASES_DIR="$PROJECT_ROOT/deployment/releases"
mkdir -p "$LOG_DIR" "$RELEASES_DIR"

DRY_RUN=0
SKIP_MODEL=0
SKIP_RUNTIME=0
SKIP_VERIFY=0
SKIP_SMOKE=0
FRONTEND_MODE="nextjs"
START_DASHBOARD=0
NO_START=0
RUNTIME_EXTRA_ARGS=()
MODEL_EXTRA_ARGS=()
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/full_deploy_${TIMESTAMP}.log"
HEALTH_REPORT="$PROJECT_ROOT/deployment/full/health_${TIMESTAMP}.json"
SMOKE_REPORT="$PROJECT_ROOT/deployment/full/smoke_${TIMESTAMP}.json"
SNAPSHOT_FILE="$RELEASES_DIR/release_snapshot_${TIMESTAMP}.tar.gz"
MANIFEST_FILE="$RELEASES_DIR/release_snapshot_${TIMESTAMP}.json"
mkdir -p "$PROJECT_ROOT/deployment/full"

log() { printf '[full-deploy] %s\n' "$*" | tee -a "$LOG_FILE"; }
die() { printf '[full-deploy][ERROR] %s\n' "$*" >&2 | tee -a "$LOG_FILE"; exit 1; }
run_cmd() { log "$*"; if [[ "$DRY_RUN" -eq 0 ]]; then "$@" 2>&1 | tee -a "$LOG_FILE"; fi }
run_shell() { log "$*"; if [[ "$DRY_RUN" -eq 0 ]]; then bash -lc "$*" 2>&1 | tee -a "$LOG_FILE"; fi }

usage() {
  cat <<USAGE
Usage: bash scripts/deploy_full_platform.sh [options]

Options:
  --skip-model            Skip model deploy step
  --skip-runtime          Skip runtime setup step
  --skip-verify           Skip health verification step
  --skip-smoke            Skip smoke test step
  --frontend-mode MODE    nextjs | static | none
  --start-dashboard       Start dashboard in runtime step
  --no-start              Setup only, do not start services
  --dry-run               Print commands only
  --                      Pass remaining args to runtime_setup_one_click.sh
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-model) SKIP_MODEL=1; shift ;;
    --skip-runtime) SKIP_RUNTIME=1; shift ;;
    --skip-verify) SKIP_VERIFY=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    --frontend-mode) FRONTEND_MODE="$2"; shift 2 ;;
    --start-dashboard) START_DASHBOARD=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; while [[ $# -gt 0 ]]; do RUNTIME_EXTRA_ARGS+=("$1"); shift; done ;;
    *) RUNTIME_EXTRA_ARGS+=("$1"); shift ;;
  esac
done

snapshot_paths=(
  "data/master_kb.xlsx"
  "data/knowledge.jsonl"
  "data/knowledge.csv"
  "data/kb_validation_report.json"
  "data/kb_manifest.json"
  "data/regression_test_set.jsonl"
  "data/regression_test_set_realistic.jsonl"
  "data/evaluation_report.json"
  "data/evaluation_details.jsonl"
  "data/serving_model.lock.json"
  "chroma_db"
  "deployment/ollama/Modelfile"
)

log "Creating snapshot archive: $SNAPSHOT_FILE"
if [[ "$DRY_RUN" -eq 0 ]]; then
  existing=()
  for path in "${snapshot_paths[@]}"; do
    [[ -e "$PROJECT_ROOT/$path" ]] && existing+=("$path")
  done
  if [[ ${#existing[@]} -gt 0 ]]; then
    tar -C "$PROJECT_ROOT" -czf "$SNAPSHOT_FILE" "${existing[@]}"
  else
    tar -C "$PROJECT_ROOT" -czf "$SNAPSHOT_FILE" README.md
  fi
  python - <<PY
import json
from datetime import datetime
from pathlib import Path
manifest = {
  "timestamp": datetime.now().isoformat(),
  "snapshot_file": str(Path(r"$SNAPSHOT_FILE")),
  "paths": ${snapshot_paths[@]+[]},
}
Path(r"$MANIFEST_FILE").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
PY
fi

if [[ "$SKIP_MODEL" -eq 0 ]]; then
  run_cmd bash "$PROJECT_ROOT/scripts/deploy_one_click.sh" ${MODEL_EXTRA_ARGS[@]:+"${MODEL_EXTRA_ARGS[@]}"}
else
  log "Skipping model deploy step"
fi

if [[ "$SKIP_RUNTIME" -eq 0 ]]; then
  runtime_cmd=(bash "$PROJECT_ROOT/scripts/runtime_setup_one_click.sh" --frontend-mode "$FRONTEND_MODE")
  [[ "$START_DASHBOARD" -eq 1 ]] && runtime_cmd+=(--start-dashboard)
  [[ "$NO_START" -eq 1 ]] && runtime_cmd+=(--no-start)
  [[ "$DRY_RUN" -eq 1 ]] && runtime_cmd+=(--dry-run)
  if [[ ${#RUNTIME_EXTRA_ARGS[@]} -gt 0 ]]; then
    runtime_cmd+=("${RUNTIME_EXTRA_ARGS[@]}")
  fi
  run_cmd "${runtime_cmd[@]}"
else
  log "Skipping runtime setup step"
fi

if [[ "$NO_START" -eq 0 && "$SKIP_VERIFY" -eq 0 ]]; then
  run_cmd python "$PROJECT_ROOT/scripts/health_verify.py" --base-url "http://127.0.0.1:8000" --output "$HEALTH_REPORT"
else
  log "Skipping health verify step"
fi

if [[ "$NO_START" -eq 0 && "$SKIP_SMOKE" -eq 0 ]]; then
  run_cmd python "$PROJECT_ROOT/scripts/smoke_test_chatbot.py" --base-url "http://127.0.0.1:8000" --test-set "$PROJECT_ROOT/data/regression_test_set_realistic.jsonl" --limit 15 --output "$SMOKE_REPORT"
else
  log "Skipping smoke test step"
fi

cat <<SUMMARY | tee -a "$LOG_FILE"

==================== Full Platform Deploy Summary ====================
Snapshot:       $SNAPSHOT_FILE
Snapshot meta:  $MANIFEST_FILE
Health report:  $HEALTH_REPORT
Smoke report:   $SMOKE_REPORT
Log file:       $LOG_FILE
Backend URL:    http://127.0.0.1:8000
Frontend mode:  $FRONTEND_MODE
Rollback:       bash scripts/rollback_release.sh --latest --restart
=====================================================================
SUMMARY
