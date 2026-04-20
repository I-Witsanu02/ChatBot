#!/usr/bin/env python3
"""Merge Unsloth/PEFT LoRA adapter into Qwen2.5 base model.

This script is intended for the user's training lineage:
- base model: Qwen/Qwen2.5-7B-Instruct
- adapter dir: up_hospital_lora

Output is a standard Hugging Face merged model directory that can then be
converted to GGUF for Ollama deployment.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge Qwen2.5 LoRA adapter into base model")
    p.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct", help="HF base model used during fine-tuning")
    p.add_argument("--adapter-dir", default="up_hospital_lora", help="Directory containing LoRA adapter files")
    p.add_argument("--output-dir", default="artifacts/merged_qwen25_7b_instruct", help="Directory to save merged HF model")
    p.add_argument("--trust-remote-code", action="store_true", help="Pass trust_remote_code=True when loading model/tokenizer")
    p.add_argument("--dtype", default="auto", choices=["auto", "float16", "bfloat16", "float32"], help="Torch dtype hint")
    return p.parse_args()


def resolve_dtype(name: str):
    import torch
    mapping = {
        "auto": "auto",
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    return mapping[name]


def main() -> None:
    args = parse_args()
    base_model = args.base_model
    adapter_dir = Path(args.adapter_dir)
    output_dir = Path(args.output_dir)
    if not adapter_dir.exists():
        raise FileNotFoundError(f"Adapter directory not found: {adapter_dir}")

    print(f"[1/4] Loading base model: {base_model}")
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    torch_dtype = resolve_dtype(args.dtype)
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=None if torch_dtype == "auto" else torch_dtype,
        trust_remote_code=args.trust_remote_code,
        device_map="auto",
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=args.trust_remote_code)

    print(f"[2/4] Loading LoRA adapter from: {adapter_dir}")
    peft_model = PeftModel.from_pretrained(model, adapter_dir)

    print("[3/4] Merging adapter into base model")
    merged_model = peft_model.merge_and_unload()

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[4/4] Saving merged HF model -> {output_dir}")
    merged_model.save_pretrained(output_dir, safe_serialization=True)
    tokenizer.save_pretrained(output_dir)

    print("✅ Merge complete")
    print(f"Merged model directory: {output_dir}")


if __name__ == "__main__":
    main()
