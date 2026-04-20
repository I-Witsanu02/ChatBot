#!/usr/bin/env python3
"""Evaluate hospital chatbot retrieval/routing on a regression test set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.policies import decide
from backend.rerank import HybridReranker
from backend.retrieval import ChromaRetriever
from backend.versioning import load_manifest, now_bangkok_iso

DEFAULT_TEST_SET = "regression_test_set_realistic.jsonl"
DEFAULT_REPORT = "evaluation_report.json"
DEFAULT_DETAILS = "evaluation_details.jsonl"
DEFAULT_MANIFEST = "kb_manifest.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate hospital chatbot retrieval/routing")
    p.add_argument("--test-set", default=DEFAULT_TEST_SET)
    p.add_argument("--report-output", default=DEFAULT_REPORT)
    p.add_argument("--details-output", default=DEFAULT_DETAILS)
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--top-k", type=int, default=10)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    tests = load_jsonl(Path(args.test_set))
    retriever = ChromaRetriever()
    reranker = HybridReranker()

    retrieval_top1 = 0
    retrieval_top3 = 0
    route_correct = 0
    source_correct = 0
    details: list[dict[str, Any]] = []
    by_case_type: dict[str, dict[str, int]] = {}

    for case in tests:
        query = case["question"]
        expected_route = case.get("expected_route")
        expected_source_id = case.get("expected_source_id")
        candidates = reranker.rerank(query, retriever.search(query, top_k=args.top_k))
        decision = decide(query, candidates)
        predicted_source_id = candidates[0].id if candidates else None
        top3_ids = [c.id for c in candidates[:3]]

        if expected_source_id and predicted_source_id == expected_source_id:
            retrieval_top1 += 1
            source_correct += 1
        if expected_source_id and expected_source_id in top3_ids:
            retrieval_top3 += 1
        if decision.action == expected_route:
            route_correct += 1

        case_type = case.get("case_type", "unknown")
        stats = by_case_type.setdefault(case_type, {"count": 0, "route_correct": 0, "source_top1": 0, "source_top3": 0})
        stats["count"] += 1
        stats["route_correct"] += int(decision.action == expected_route)
        stats["source_top1"] += int(bool(expected_source_id) and predicted_source_id == expected_source_id)
        stats["source_top3"] += int(bool(expected_source_id) and expected_source_id in top3_ids)

        details.append({
            "id": case["id"],
            "case_type": case_type,
            "question": query,
            "expected_route": expected_route,
            "predicted_route": decision.action,
            "expected_source_id": expected_source_id,
            "predicted_source_id": predicted_source_id,
            "top3_ids": top3_ids,
            "confidence": round(decision.confidence, 4),
            "reason": decision.reason,
            "pass_route": decision.action == expected_route,
            "pass_source_top1": bool(expected_source_id) and predicted_source_id == expected_source_id,
            "pass_source_top3": bool(expected_source_id) and expected_source_id in top3_ids,
        })

    total = max(len(tests), 1)
    answer_cases = max(sum(1 for t in tests if t.get("expected_source_id")), 1)
    report = {
        "generated_at": now_bangkok_iso(),
        "kb_manifest": load_manifest(Path(args.manifest)),
        "test_case_count": len(tests),
        "metrics": {
            "route_accuracy": round(route_correct / total, 4),
            "retrieval_top1": round(retrieval_top1 / answer_cases, 4),
            "retrieval_top3": round(retrieval_top3 / answer_cases, 4),
            "source_accuracy": round(source_correct / answer_cases, 4),
        },
        "by_case_type": by_case_type,
        "top_failures": [d for d in details if not d["pass_route"] or (d["expected_source_id"] and not d["pass_source_top1"])][:20],
    }

    Path(args.report_output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(Path(args.details_output), details)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
