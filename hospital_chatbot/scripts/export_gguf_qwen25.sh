#!/usr/bin/env bash
set -euo pipefail

# Convert merged HF model to GGUF and quantize it.
# Example:
#   bash scripts/export_gguf_qwen25.sh artifacts/merged_qwen25_7b_instruct ~/llama.cpp artifacts/gguf

MERGED_DIR="${1:-artifacts/merged_qwen25_7b_instruct}"
LLAMA_CPP_DIR="${2:-$HOME/llama.cpp}"
OUT_DIR="${3:-artifacts/gguf}"
F16_NAME="merged-qwen2.5-7b-instruct-f16.gguf"
Q4_NAME="merged-qwen2.5-7b-instruct-q4_k_m.gguf"

mkdir -p "$OUT_DIR"

echo "[1/3] Convert HF -> GGUF (F16)"
python "$LLAMA_CPP_DIR/convert_hf_to_gguf.py" "$MERGED_DIR" --outfile "$OUT_DIR/$F16_NAME" --outtype f16

echo "[2/3] Quantize -> Q4_K_M"
"$LLAMA_CPP_DIR/llama-quantize" "$OUT_DIR/$F16_NAME" "$OUT_DIR/$Q4_NAME" Q4_K_M

echo "[3/3] Done"
echo "F16 GGUF: $OUT_DIR/$F16_NAME"
echo "Q4 GGUF:  $OUT_DIR/$Q4_NAME"
