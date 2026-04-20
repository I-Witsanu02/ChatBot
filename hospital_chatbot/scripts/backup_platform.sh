#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
NAME="${1:-hospital_platform_backup_${TIMESTAMP}}"
OUT_DIR="$BACKUP_DIR/$NAME"
ARCHIVE="$BACKUP_DIR/${NAME}.tar.gz"

mkdir -p "$BACKUP_DIR" "$OUT_DIR"

copy_if_exists() {
  local path="$1"
  if [[ -e "$path" ]]; then
    mkdir -p "$OUT_DIR/$(dirname "$path")"
    cp -R "$PROJECT_ROOT/$path" "$OUT_DIR/$path"
  fi
}

copy_if_exists data
copy_if_exists chroma_db
copy_if_exists logs
copy_if_exists deployment/runtime/logs
copy_if_exists deployment/model/logs
copy_if_exists deployment/releases

python - <<PY > "$OUT_DIR/backup_manifest.json"
import json, os, hashlib, time
from pathlib import Path
root = Path(r"$PROJECT_ROOT")
out = Path(r"$OUT_DIR")
files = []
for p in out.rglob('*'):
    if p.is_file() and p.name != 'backup_manifest.json':
        rel = p.relative_to(out).as_posix()
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        files.append({'path': rel, 'size': p.stat().st_size, 'sha256': h})
json.dump({'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'files': files}, open(out/'backup_manifest.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY

tar -C "$BACKUP_DIR" -czf "$ARCHIVE" "$NAME"
rm -rf "$OUT_DIR"
echo "$ARCHIVE"
