#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
SNAPSHOT_BEFORE_RESTORE=1
ARCHIVE=""

usage() {
  cat <<USAGE
Usage: bash scripts/restore_platform_backup.sh --archive PATH [--no-snapshot]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="$2"; shift 2 ;;
    --no-snapshot) SNAPSHOT_BEFORE_RESTORE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$ARCHIVE" ]] || { usage; exit 1; }
[[ -f "$ARCHIVE" ]] || { echo "Archive not found: $ARCHIVE" >&2; exit 1; }

if [[ "$SNAPSHOT_BEFORE_RESTORE" -eq 1 ]]; then
  bash "$PROJECT_ROOT/scripts/backup_platform.sh" "pre_restore_$(date +%Y%m%d_%H%M%S)" >/dev/null
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

tar -xzf "$ARCHIVE" -C "$TMP_DIR"
SRC_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -n "$SRC_DIR" ]] || { echo "Invalid archive structure" >&2; exit 1; }

for item in data chroma_db logs deployment; do
  if [[ -e "$SRC_DIR/$item" ]]; then
    rm -rf "$PROJECT_ROOT/$item"
    mkdir -p "$(dirname "$PROJECT_ROOT/$item")"
    cp -R "$SRC_DIR/$item" "$PROJECT_ROOT/$item"
  fi
done

echo "Restore completed from $ARCHIVE"
