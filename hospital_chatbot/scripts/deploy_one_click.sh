#!/usr/bin/env bash
set -Eeuo pipefail

# One-click deployment for the hospital chatbot serving model.
# Steps:
#  1) merge LoRA into Qwen2.5 base model
#  2) export merged model to GGUF (F16 + Q4_K_M)
#  3) create custom Ollama model
#  4) lock serving model metadata
#  5) verify Ollama model exists and matches the lock file
#
# Example:
#   bash scripts/deploy_one_click.sh
#   bash scripts/deploy_one_click.sh --skip-merge --skip-export
#   bash scripts/deploy_one_click.sh --dry-run

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/deployment/logs"
mkdir -p "$LOG_DIR"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/deploy_${RUN_ID}.log"

BASE_MODEL="Qwen/Qwen2.5-7B-Instruct"
ADAPTER_DIR="$ROOT_DIR/up_hospital_lora"
MERGED_DIR="$ROOT_DIR/artifacts/merged_qwen25_7b_instruct"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
GGUF_DIR="$ROOT_DIR/artifacts/gguf"
GGUF_Q4_PATH="$GGUF_DIR/merged-qwen2.5-7b-instruct-q4_k_m.gguf"
OLLAMA_MODEL_NAME="up-hospital-qwen2.5-7b-instruct"
LOCK_OUTPUT="$ROOT_DIR/data/serving_model.lock.json"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
TRUST_REMOTE_CODE="false"
DTYPE="auto"
RESET_GGUF="false"
SKIP_MERGE="false"
SKIP_EXPORT="false"
SKIP_CREATE="false"
SKIP_LOCK="false"
SKIP_VERIFY="false"
DRY_RUN="false"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

run_cmd() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: $*"
  else
    log "RUN: $*"
    "$@" 2>&1 | tee -a "$LOG_FILE"
  fi
}

usage() {
  cat <<USAGE
Usage: bash scripts/deploy_one_click.sh [options]

Options:
  --base-model <name>           Hugging Face base model (default: $BASE_MODEL)
  --adapter-dir <path>          LoRA adapter directory (default: $ADAPTER_DIR)
  --merged-dir <path>           Output directory for merged HF model (default: $MERGED_DIR)
  --llama-cpp-dir <path>        llama.cpp directory (default: $LLAMA_CPP_DIR)
  --gguf-dir <path>             Output directory for GGUF files (default: $GGUF_DIR)
  --ollama-model <name>         Ollama model name (default: $OLLAMA_MODEL_NAME)
  --lock-output <path>          Serving-model lock path (default: $LOCK_OUTPUT)
  --ollama-base-url <url>       Ollama base URL (default: $OLLAMA_BASE_URL)
  --dtype <auto|float16|bfloat16|float32>
  --trust-remote-code           Pass trust_remote_code to merge script
  --reset-gguf                  Delete existing GGUF output before export
  --skip-merge                  Skip merge step
  --skip-export                 Skip GGUF export step
  --skip-create                 Skip ollama create step
  --skip-lock                   Skip lock-file generation
  --skip-verify                 Skip verification step
  --dry-run                     Print commands without executing
  -h, --help                    Show this help message
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-model) BASE_MODEL="$2"; shift 2 ;;
    --adapter-dir) ADAPTER_DIR="$2"; shift 2 ;;
    --merged-dir) MERGED_DIR="$2"; shift 2 ;;
    --llama-cpp-dir) LLAMA_CPP_DIR="$2"; shift 2 ;;
    --gguf-dir) GGUF_DIR="$2"; GGUF_Q4_PATH="$GGUF_DIR/merged-qwen2.5-7b-instruct-q4_k_m.gguf"; shift 2 ;;
    --ollama-model) OLLAMA_MODEL_NAME="$2"; shift 2 ;;
    --lock-output) LOCK_OUTPUT="$2"; shift 2 ;;
    --ollama-base-url) OLLAMA_BASE_URL="$2"; shift 2 ;;
    --dtype) DTYPE="$2"; shift 2 ;;
    --trust-remote-code) TRUST_REMOTE_CODE="true"; shift ;;
    --reset-gguf) RESET_GGUF="true"; shift ;;
    --skip-merge) SKIP_MERGE="true"; shift ;;
    --skip-export) SKIP_EXPORT="true"; shift ;;
    --skip-create) SKIP_CREATE="true"; shift ;;
    --skip-lock) SKIP_LOCK="true"; shift ;;
    --skip-verify) SKIP_VERIFY="true"; shift ;;
    --dry-run) DRY_RUN="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

on_error() {
  local exit_code=$?
  log "❌ Deployment failed with exit code ${exit_code}. Check log: $LOG_FILE"
  exit "$exit_code"
}
trap on_error ERR

check_exists() {
  local kind="$1"
  local path="$2"
  if [[ ! -e "$path" ]]; then
    log "Missing ${kind}: $path"
    exit 1
  fi
}

log "Starting one-click deploy"
log "Log file: $LOG_FILE"
log "Project root: $ROOT_DIR"

check_exists "project root" "$ROOT_DIR"
check_exists "merge script" "$ROOT_DIR/scripts/merge_lora_qwen25.py"
check_exists "export script" "$ROOT_DIR/scripts/export_gguf_qwen25.sh"
check_exists "create script" "$ROOT_DIR/scripts/create_ollama_model.sh"
check_exists "verify script" "$ROOT_DIR/scripts/verify_ollama_serving.py"
check_exists "lock script" "$ROOT_DIR/scripts/lock_serving_model.py"

if [[ "$SKIP_MERGE" != "true" ]]; then
  check_exists "adapter directory" "$ADAPTER_DIR"
fi

if [[ "$SKIP_EXPORT" != "true" ]]; then
  check_exists "llama.cpp directory" "$LLAMA_CPP_DIR"
  check_exists "convert_hf_to_gguf.py" "$LLAMA_CPP_DIR/convert_hf_to_gguf.py"
  if [[ ! -x "$LLAMA_CPP_DIR/llama-quantize" && ! -x "$LLAMA_CPP_DIR/build/bin/llama-quantize" ]]; then
    log "Missing llama-quantize binary in $LLAMA_CPP_DIR"
    exit 1
  fi
fi

if [[ "$SKIP_CREATE" != "true" || "$SKIP_VERIFY" != "true" ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    log "ollama command not found in PATH"
    exit 1
  fi
fi

mkdir -p "$(dirname "$LOCK_OUTPUT")" "$GGUF_DIR" "$(dirname "$MERGED_DIR")"

if [[ "$RESET_GGUF" == "true" && "$SKIP_EXPORT" != "true" ]]; then
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: rm -rf $GGUF_DIR"
  else
    log "Removing existing GGUF output: $GGUF_DIR"
    rm -rf "$GGUF_DIR"
    mkdir -p "$GGUF_DIR"
  fi
fi

if [[ "$SKIP_MERGE" != "true" ]]; then
  log "Step 1/5: merge LoRA into base model"
  cmd=(python "$ROOT_DIR/scripts/merge_lora_qwen25.py" --base-model "$BASE_MODEL" --adapter-dir "$ADAPTER_DIR" --output-dir "$MERGED_DIR" --dtype "$DTYPE")
  if [[ "$TRUST_REMOTE_CODE" == "true" ]]; then
    cmd+=(--trust-remote-code)
  fi
  run_cmd "${cmd[@]}"
else
  log "Step 1/5 skipped: merge"
fi

if [[ "$SKIP_EXPORT" != "true" ]]; then
  log "Step 2/5: export merged model to GGUF"
  run_cmd bash "$ROOT_DIR/scripts/export_gguf_qwen25.sh" "$MERGED_DIR" "$LLAMA_CPP_DIR" "$GGUF_DIR"
else
  log "Step 2/5 skipped: export"
fi

if [[ "$SKIP_CREATE" != "true" ]]; then
  log "Step 3/5: create custom Ollama model"
  check_exists "GGUF model" "$GGUF_Q4_PATH"
  run_cmd bash "$ROOT_DIR/scripts/create_ollama_model.sh" "$GGUF_Q4_PATH" "$OLLAMA_MODEL_NAME"
else
  log "Step 3/5 skipped: create Ollama model"
fi

if [[ "$SKIP_LOCK" != "true" ]]; then
  log "Step 4/5: write serving-model lock file"
  run_cmd python "$ROOT_DIR/scripts/lock_serving_model.py" --serving-model-name "$OLLAMA_MODEL_NAME" --training-base-model "$BASE_MODEL" --lock-output "$LOCK_OUTPUT"
else
  log "Step 4/5 skipped: lock"
fi

if [[ "$SKIP_VERIFY" != "true" ]]; then
  log "Step 5/5: verify Ollama model"
  run_cmd python "$ROOT_DIR/scripts/verify_ollama_serving.py" --lock "$LOCK_OUTPUT" --ollama-base-url "$OLLAMA_BASE_URL"
else
  log "Step 5/5 skipped: verify"
fi

if [[ "$DRY_RUN" == "true" ]]; then
  log "✅ Dry-run complete"
else
  log "✅ One-click deploy complete"
fi

cat <<SUMMARY | tee -a "$LOG_FILE"

Summary
-------
Base model:        $BASE_MODEL
Adapter dir:       $ADAPTER_DIR
Merged model dir:  $MERGED_DIR
GGUF dir:          $GGUF_DIR
Ollama model:      $OLLAMA_MODEL_NAME
Lock file:         $LOCK_OUTPUT
Ollama base URL:   $OLLAMA_BASE_URL
Log file:          $LOG_FILE
SUMMARY
