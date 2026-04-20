#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_FILE="${1:-$PROJECT_ROOT/deployment/nginx/.htpasswd}"
USER_NAME="${2:-admin}"

if [[ -z "${3:-}" ]]; then
  echo "Usage: bash scripts/create_nginx_htpasswd.sh [outfile] [username] [password]" >&2
  exit 1
fi
PASSWORD="$3"

mkdir -p "$(dirname "$OUT_FILE")"
printf '%s:%s\n' "$USER_NAME" "$(openssl passwd -apr1 "$PASSWORD")" > "$OUT_FILE"
echo "Wrote $OUT_FILE"
