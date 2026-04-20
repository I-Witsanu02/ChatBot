"""Serving-model lock and runtime validation.

V14 default runtime is optimized for the models the user already has locally:
- Embedding: bge-m3 via Ollama
- Chat model: scb10x/typhoon2.5-qwen3-4b via Ollama

The fine-tuned Qwen2.5 path remains documented as the long-term production
path, but the temporary runtime defaults are set to the local models that are
already available on the user's machine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_LOCK_PATH = "data/serving_model.lock.json"


def default_lock_payload() -> dict[str, Any]:
    return {
        "training": {
            "framework": "unsloth",
            "base_model_hf": "Qwen/Qwen2.5-7B-Instruct",
            "adapter_dir": "up_hospital_lora",
            "adapter_type": "lora",
            "notes": "Original fine-tune script uses Qwen/Qwen2.5-7B-Instruct as the base model.",
        },
        "serving": {
            "provider": "ollama",
            "mode": "temporary_local_runtime_model",
            "model_name": os.getenv("OLLAMA_MODEL", "scb10x/typhoon2.5-qwen3-4b:latest"),
            "base_model_reference": "scb10x/typhoon2.5-qwen3-4b:latest",
            "endpoint": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            "must_match_training_base": False,
            "disallow_runtime_model_override": False,
            "notes": "Temporary serving model selected from locally installed Ollama models for Thai conversational quality. Replace with merged fine-tuned custom model later if required.",
        },
        "embedding": {
            "provider": os.getenv("EMBEDDING_PROVIDER", "ollama"),
            "model_name": os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest"),
            "endpoint": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        },
        "reranker": {
            "provider": "hybrid_lexical_vector",
            "model_name": os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        },
        "deployment_notes": {
            "preferred_current_runtime": {
                "embedding": "bge-m3:latest",
                "chat": "scb10x/typhoon2.5-qwen3-4b:latest",
            },
            "future_upgrade_path": "Merge LoRA with Qwen2.5-7B-Instruct, export GGUF, and replace the temporary Ollama chat model when the fine-tuned model is ready.",
        },
    }


def ensure_lock_file(path: Path) -> dict[str, Any]:
    if path.exists():
        return load_lock(path)
    payload = default_lock_payload()
    save_lock(path, payload)
    return payload


def load_lock(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_lock(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def runtime_summary(lock_path: Path) -> dict[str, Any]:
    lock = ensure_lock_file(lock_path)
    serving = lock.get("serving", {})
    embedding = lock.get("embedding", {})
    configured_provider = serving.get("provider")
    configured_model = serving.get("model_name")
    env_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    env_model = os.getenv("OLLAMA_MODEL") or configured_model
    env_embed = os.getenv("OLLAMA_EMBED_MODEL") or embedding.get("model_name")
    warnings: list[str] = []
    if not env_model:
        warnings.append("No OLLAMA_MODEL is configured.")
    if not env_embed:
        warnings.append("No OLLAMA_EMBED_MODEL is configured.")
    return {
        "lock_path": str(lock_path),
        "configured_provider": configured_provider,
        "configured_model": configured_model,
        "runtime_endpoint": env_base_url,
        "runtime_model": env_model,
        "runtime_embedding_model": env_embed,
        "embedding_provider": embedding.get("provider"),
        "warnings": warnings,
        "lock": lock,
    }
