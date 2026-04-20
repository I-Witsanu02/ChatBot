#!/usr/bin/env bash
set -euo pipefail

# Create a custom Ollama model from the merged GGUF and bundled Modelfile.
# Example:
#   bash scripts/create_ollama_model.sh artifacts/gguf/merged-qwen2.5-7b-instruct-q4_k_m.gguf up-hospital-qwen2.5-7b-instruct

GGUF_PATH="${1:-artifacts/gguf/merged-qwen2.5-7b-instruct-q4_k_m.gguf}"
MODEL_NAME="${2:-up-hospital-qwen2.5-7b-instruct}"
DEPLOY_DIR="deployment/ollama"
MODFILE="$DEPLOY_DIR/Modelfile"

if [[ ! -f "$GGUF_PATH" ]]; then
  echo "GGUF not found: $GGUF_PATH" >&2
  exit 1
fi

mkdir -p "$DEPLOY_DIR"
cp "$GGUF_PATH" "$DEPLOY_DIR/$(basename "$GGUF_PATH")"
GGUF_BASENAME="$(basename "$GGUF_PATH")"

cat > "$MODFILE" <<EOF
FROM ./$GGUF_BASENAME

SYSTEM "คุณคือผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยา ตอบจากข้อมูลในระบบและบริบทที่ backend ส่งมาเท่านั้น หากไม่พบข้อมูลหรือข้อมูลไม่ชัดเจน ให้แนะนำติดต่อเจ้าหน้าที่"
PARAMETER temperature 0.1
PARAMETER num_ctx 8192
EOF

echo "Creating Ollama model: $MODEL_NAME"
(
  cd "$DEPLOY_DIR"
  ollama create "$MODEL_NAME" -f Modelfile
)

echo "✅ Created Ollama model: $MODEL_NAME"
