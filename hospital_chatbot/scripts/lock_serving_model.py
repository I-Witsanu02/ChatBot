#!/usr/bin/env python3
"""Create a serving-model lock file and Ollama deployment templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_LOCK = "data/serving_model.lock.json"
DEFAULT_MODEL_NAME = "up-hospital-qwen2.5-7b-instruct"
DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_OLLAMA_BASE = "qwen2.5:7b-instruct"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create serving model lock + deployment templates")
    p.add_argument("--lock-output", default=DEFAULT_LOCK)
    p.add_argument("--training-base-model", default=DEFAULT_BASE_MODEL)
    p.add_argument("--adapter-dir", default="up_hospital_lora")
    p.add_argument("--serving-model-name", default=DEFAULT_MODEL_NAME)
    p.add_argument("--ollama-base-model", default=DEFAULT_OLLAMA_BASE)
    p.add_argument("--ollama-endpoint", default="http://127.0.0.1:11434")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    lock_path = Path(args.lock_output)
    payload = {
        "training": {
            "framework": "unsloth",
            "base_model_hf": args.training_base_model,
            "adapter_dir": args.adapter_dir,
            "adapter_type": "lora",
        },
        "serving": {
            "provider": "ollama",
            "mode": "custom_ollama_model_from_merged_gguf",
            "model_name": args.serving_model_name,
            "base_model_reference": args.ollama_base_model,
            "endpoint": args.ollama_endpoint,
            "must_match_training_base": True,
            "disallow_runtime_model_override": True,
        },
        "deployment_notes": {
            "preferred_path": "Merge LoRA -> GGUF -> custom Ollama model",
            "forbidden_examples": ["scb10x/typhoon2.5-qwen3-4b:latest", "qwen3:4b"],
        },
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    project_root = lock_path.parents[1]
    model_dir = project_root / "deployment" / "ollama"
    model_dir.mkdir(parents=True, exist_ok=True)
    modelfile = model_dir / "Modelfile"
    modelfile.write_text(
        'FROM ./merged-qwen2.5-7b-instruct.gguf\n\n'
        'SYSTEM "คุณคือผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยา ตอบจากข้อมูลที่ระบบส่งมาเท่านั้น"\n'
        'PARAMETER temperature 0.1\n',
        encoding="utf-8",
    )
    readme = model_dir / "README.md"
    readme.write_text(
        "# Ollama deployment\n\n"
        "1. Merge the LoRA adapter into the same base model used during training.\n"
        "2. Convert the merged model to GGUF.\n"
        "3. Put the merged GGUF next to this Modelfile.\n"
        f"4. Run `ollama create {args.serving_model_name} -f Modelfile`.\n"
        f"5. Run `ollama run {args.serving_model_name}` to verify.\n",
        encoding="utf-8",
    )
    print(f"Wrote lock file -> {lock_path}")
    print(f"Wrote Ollama template -> {modelfile}")


if __name__ == "__main__":
    main()
