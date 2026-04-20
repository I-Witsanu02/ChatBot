#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASES_DIR="$PROJECT_ROOT/deployment/releases"
TARGET_ARCHIVE=""
USE_LATEST=0
RESTART=0
DRY_RUN=0

usage() {
  cat <<USAGE
Usage: bash scripts/rollback_release.sh [options]

Options:
  --archive PATH     Snapshot archive to restore
  --latest           Restore latest snapshot archive
  --restart          Restart runtime after restore
  --dry-run          Print actions only
  -h, --help         Show this help
USAGE
}

log() { printf '[rollback] %s\n' "$*"; }
die() { printf '[rollback][ERROR] %s\n' "$*" >&2; exit 1; }
run_cmd() { log "$*"; if [[ "$DRY_RUN" -eq 0 ]]; then "$@"; fi }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) TARGET_ARCHIVE="$2"; shift 2 ;;
    --latest) USE_LATEST=1; shift ;;
    --restart) RESTART=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

if [[ "$USE_LATEST" -eq 1 ]]; then
  TARGET_ARCHIVE="$(ls -1t "$RELEASES_DIR"/release_snapshot_*.tar.gz 2>/dev/null | head -1 || true)"
fi
[[ -n "$TARGET_ARCHIVE" ]] || die "Specify --archive or --latest"
[[ -f "$TARGET_ARCHIVE" ]] || die "Archive not found: $TARGET_ARCHIVE"

run_cmd bash "$PROJECT_ROOT/scripts/stop_runtime.sh" --quiet
run_cmd tar -C "$PROJECT_ROOT" -xzf "$TARGET_ARCHIVE"

if [[ "$RESTART" -eq 1 ]]; then
  run_cmd bash "$PROJECT_ROOT/scripts/runtime_setup_one_click.sh" --skip-install --skip-build --skip-reindex --skip-testset --skip-eval
fi

log "Rollback complete from $TARGET_ARCHIVE"
