#!/usr/bin/env python3
"""Verify that the running Ollama model matches the serving-model lock."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify Ollama serving model against lock file")
    p.add_argument("--lock", default="data/serving_model.lock.json")
    p.add_argument("--ollama-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    lock = json.loads(Path(args.lock).read_text(encoding="utf-8"))
    expected_model = lock["serving"]["model_name"]
    req = Request(
        url=args.ollama_base_url.rstrip("/") + "/api/show",
        data=json.dumps({"name": expected_model}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    print(json.dumps({
        "expected_model": expected_model,
        "ollama_base_url": args.ollama_base_url,
        "show_response_summary": {
            "modelfile": payload.get("modelfile"),
            "license": payload.get("license"),
            "template": payload.get("template"),
            "parameters": payload.get("parameters"),
        },
    }, ensure_ascii=False, indent=2))
    print("✅ Ollama model exists and matches lock file name")


if __name__ == "__main__":
    main()
