#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any


def post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_cases(path: Path, limit: int) -> list[dict[str, Any]]:
    cases = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
            if len(cases) >= limit:
                break
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Run smoke tests against /chat")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--test-set", default="data/regression_test_set_realistic.jsonl")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    cases = load_cases(Path(args.test_set), args.limit)
    results = []
    passed = 0

    for case in cases:
        payload = {"question": case["question"], "top_k": 8}
        resp = post_json(f"{base}/chat", payload)
        ok = True
        reasons: list[str] = []
        if case.get("expected_route") and resp.get("route") != case["expected_route"]:
            ok = False
            reasons.append(f"route expected={case.get('expected_route')} actual={resp.get('route')}")
        if case.get("expected_source_id") and resp.get("source_id") != case["expected_source_id"]:
            ok = False
            reasons.append(f"source expected={case.get('expected_source_id')} actual={resp.get('source_id')}")
        if case.get("expected_category") and resp.get("selected_category") != case["expected_category"]:
            ok = False
            reasons.append(f"category expected={case.get('expected_category')} actual={resp.get('selected_category')}")
        if ok:
            passed += 1
        results.append({
            "id": case.get("id"),
            "question": case.get("question"),
            "expected_route": case.get("expected_route"),
            "actual_route": resp.get("route"),
            "expected_source_id": case.get("expected_source_id"),
            "actual_source_id": resp.get("source_id"),
            "expected_category": case.get("expected_category"),
            "actual_category": resp.get("selected_category"),
            "ok": ok,
            "reasons": reasons,
        })

    report = {
        "base_url": base,
        "test_set": str(args.test_set),
        "limit": args.limit,
        "total": len(results),
        "passed": passed,
        "pass_rate": (passed / len(results)) if results else 0.0,
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    return 0 if report["pass_rate"] >= 0.7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
