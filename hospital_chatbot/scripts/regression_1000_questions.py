#!/usr/bin/env python3
"""Expanded >=1000-case regression suite for UPH Hospital Chatbot.

Builds on regression_100_questions.py and expands coverage with:
- exact FAQ wording
- paraphrases
- short queries
- typos / aliases / abbreviations
- doctor / department schedule wording
- multi-turn follow-up flows
- reset / goHome flows
- naked slot queries after context
- unsupported hospital-scope edge cases
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import regression_100_questions as reg100

PREFIXES = [
    "",
    "ขอข้อมูล",
    "ขอสอบถาม",
    "อยากทราบ",
    "รบกวนสอบถาม",
    "ช่วยเช็กให้หน่อย",
]

SUFFIXES = [
    "",
    "ครับ",
    "ค่ะ",
    "ได้ไหม",
    "หน่อย",
]

EXTRA_VARIANTS: dict[str, list[str]] = {
    "วัคซีน": ["ฉีดวัคซีน", "มีวัคซีนอะไรบ้าง", "เรื่องวัคซีน"],
    "วัคซีน HPV": ["hpv", "ฉีด hpv", "วัคซีนมะเร็งปากมดลูก"],
    "วัคซีนพิษสุนัขบ้า": ["พิษสุนัขบ้า", "วัคซีนหมากัด", "rabies vaccine"],
    "วัคซีนบาดทะยัก": ["บาดทะยัก", "tetanus", "ฉีดบาดทะยัก"],
    "ตารางแพทย์": ["ตารางหมอ", "หมอออกตรวจ", "มีหมอวันไหน"],
    "หมอกระดูกออกวันไหน": ["หมอกระดูกวันไหน", "ออร์โธออกวันไหน", "กระดูกและข้อวันไหน"],
    "หมอผิวหนังวันไหน": ["หมอหนังวันไหน", "ผิวหนังวันไหน", "คลินิกผิวหนังวันไหน"],
    "หมอตาวันนี้มีไหม": ["หมอตาวันนี้", "จักษุวันนี้มีไหม", "คลินิกตาวันนี้มีไหม"],
    "สูตินรีเวชวันไหน": ["สูติวันไหน", "นรีเวชวันไหน", "ฝากครรภ์วันไหน"],
    "กุมารแพทย์วันไหน": ["หมอเด็กวันไหน", "กุมารวันไหน", "หมอเด็กออกวันไหน"],
    "ตรวจสุขภาพ": ["ตรวจร่างกาย", "เช็กสุขภาพ", "check up"],
    "โปรแกรมตรวจสุขภาพ": ["แพ็กเกจตรวจสุขภาพ", "แพคเกจตรวจสุขภาพ", "โปรแกรม check up"],
    "ตรวจสุขภาพบริษัท": ["ตรวจสุขภาพพนักงาน", "ตรวจสุขภาพองค์กร", "ตรวจสุขภาพหน่วยงาน"],
    "ใบรับรองแพทย์": ["ใบรับรอง", "ขอใบรับรองแพทย์", "เอกสารแพทย์"],
    "ใบรับรองแพทย์ 5 โรค": ["ใบรับรอง 5 โรค", "ใบรับรองสมัครงาน", "ใบรับรองเรียนต่อ"],
    "สิทธิการรักษา": ["เช็กสิทธิ", "ตรวจสอบสิทธิ", "สิทธิรักษา"],
    "ขอประวัติการรักษา": ["เวชระเบียน", "ขอเวชระเบียน", "ขอประวัติคนไข้"],
    "ค่ารักษา": ["ค่าใช้จ่าย", "ค่ารักษาพยาบาล", "ค่ารักษาเท่าไหร่"],
    "ติดต่อการเงิน": ["การเงิน", "ติดต่อแผนกการเงิน", "เบอร์การเงิน"],
    "ฟอกไต": ["ไตเทียม", "ล้างไต", "ศูนย์ไตเทียม"],
    "บริจาคเลือด": ["ให้เลือด", "ธนาคารเลือด", "บริจาคเลือดวันไหน"],
    "หมอฟัน": ["ทันตกรรม", "ทำฟัน", "โรงพยาบาลทันตกรรม"],
    "สมัครงาน": ["งานบุคคล", "รับสมัครงาน", "hr"],
    "ENT วันไหน": ["หูคอจมูกวันไหน", "หมอหูคอจมูกวันไหน", "ent clinic วันไหน"],
    "OPD 1 เปิดกี่โมง": ["opd1 เปิดกี่โมง", "ผู้ป่วยนอก 1 เปิดกี่โมง", "opd 1 เวลาอะไร"],
    "OPD 2 มีหมอผิวหนังไหม": ["opd2 มีหมอผิวหนังไหม", "ผู้ป่วยนอก 2 มีหมอผิวหนังไหม", "opd 2 ผิวหนังไหม"],
}

TYPO_VARIANTS: dict[str, list[str]] = {
    "วัคซีน": ["วักซีน", "วัปซีน", "วคซีน"],
    "หมอผิวหนังวันไหน": ["หมอหนังวันไหน", "ผิวหนังวันใหน", "หมอผิวหนังวั้นไหน"],
    "หมอกระดูกออกวันไหน": ["หมอกระดุกออกวันไหน", "หมอกระดูกออกวันใหน", "กระดุกวันไหน"],
    "ตรวจสุขภาพ": ["ตรจสุขภาพ", "ตรวจสขภาพ", "ตรวดสุขภาพ"],
    "ลืมวันนัด": ["ลืมนัด", "ลืมวันัด", "ลืมวนนัด"],
    "หมอฟัน": ["หมอฟัล", "หมอฟันน", "หมอฟันน์"],
    "ฟอกไต": ["ฟอกไต้", "ฟอกไตใช้สิทธิไรได้บ้าง", "ฟอกไตมีไหม"],
    "บริจาคเลือด": ["บริจา่คเลือด", "บริจากเลือด", "บรจาคเลือด"],
}

UNSUPPORTED_CASES = [
    {
        "id": "unsup-001",
        "question": "มีบริการ MRI 24 ชั่วโมงไหม",
        "expected_route": "fallback",
        "expected_category": None,
        "case_type": "unsupported",
    },
    {
        "id": "unsup-002",
        "question": "ผ่าตัดหัวใจราคาเท่าไหร่",
        "expected_route": "fallback",
        "expected_category": None,
        "case_type": "unsupported",
    },
    {
        "id": "unsup-003",
        "question": "มีวัคซีนเดินทางต่างประเทศครบทุกตัวไหม",
        "expected_route": "clarify",
        "expected_category": "วัคซีน",
        "case_type": "unsupported",
    },
    {
        "id": "unsup-004",
        "question": "จองห้อง VIP ออนไลน์ได้ไหม",
        "expected_route": "fallback",
        "expected_category": None,
        "case_type": "unsupported",
    },
]


def normalize_space(text: str) -> str:
    return " ".join(str(text or "").split())


def make_variant(case: dict[str, Any], question: str, *, suffix_id: str, session_id: str | None = None) -> dict[str, Any]:
    variant = dict(case)
    variant["id"] = f"{case['id']}::{suffix_id}"
    variant["question"] = normalize_space(question)
    if session_id:
        variant["session_id"] = session_id
    return variant


def paraphrase_variants(question: str) -> list[str]:
    q = normalize_space(question)
    variants = {q}
    for prefix in PREFIXES:
        for suffix in SUFFIXES:
            text = f"{prefix} {q} {suffix}".strip()
            variants.add(normalize_space(text))
    for extra in EXTRA_VARIANTS.get(q, []):
        variants.add(normalize_space(extra))
    for typo in TYPO_VARIANTS.get(q, []):
        variants.add(normalize_space(typo))
    return [item for item in variants if item]


def expand_base_cases(base_cases: list[dict[str, Any]], target_min: int) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add_case(case: dict[str, Any]) -> None:
        key = (case["id"], case["question"], case.get("session_id"))
        if key in seen:
            return
        seen.add(key)
        expanded.append(case)

    for case in base_cases:
        add_case(case)
        for idx, variant_q in enumerate(paraphrase_variants(case["question"])):
            if idx == 0:
                continue
            add_case(make_variant(case, variant_q, suffix_id=f"p{idx:02d}", session_id=case.get("session_id")))

    # Multi-turn follow-up expansions
    flow_seed = [
        ("วัคซีน", "วัคซีนไข้หวัดใหญ่", "ติดต่อที่ไหน"),
        ("วัคซีน", "วัคซีนพิษสุนัขบ้า", "ราคาเท่าไหร่"),
        ("ตารางแพทย์", "หมอกระดูกออกวันไหน", "เปิดวันไหน"),
        ("ตรวจสุขภาพ", "ตรวจสุขภาพบริษัท", "ใช้สิทธิเบิกตรงได้ไหม"),
        ("สิทธิการรักษา", "ย้ายสิทธิ", "ติดต่อที่ไหน"),
    ]
    flow_counter = 1
    for q1, q2, q3 in flow_seed:
        sid = f"reg1000-flow-{flow_counter:03d}"
        flow_counter += 1
        for turn_idx, q in enumerate((q1, q2, q3), start=1):
            template = next((case for case in base_cases if normalize_space(case["question"]) == q), None)
            if template is None:
                continue
            add_case(make_variant(template, q, suffix_id=f"flow{flow_counter:03d}-t{turn_idx}", session_id=sid))

    # Reset flows
    reset_templates = [case for case in base_cases if case["id"].startswith("reset-")]
    starter_templates = [case for case in base_cases if case["id"] in {"vac-F", "apt-E", "hc-A", "rec-A"}]
    for idx, starter in enumerate(starter_templates, start=1):
        sid = f"reg1000-reset-{idx:03d}"
        add_case(make_variant(starter, starter["question"], suffix_id="seed", session_id=sid))
        for reset_case in reset_templates:
            add_case(make_variant(reset_case, reset_case["question"], suffix_id=f"after-{starter['id']}", session_id=sid))

    # Unsupported edges
    for case in UNSUPPORTED_CASES:
        add_case(case)
        for idx, variant_q in enumerate(paraphrase_variants(case["question"])):
            if idx == 0:
                continue
            add_case(make_variant(case, variant_q, suffix_id=f"u{idx:02d}"))

    # Ensure >= target_min by reusing base paraphrases with stable ids
    if len(expanded) < target_min:
        loop = 0
        while len(expanded) < target_min:
            loop += 1
            for case in base_cases:
                for idx, variant_q in enumerate(paraphrase_variants(case["question"])):
                    add_case(make_variant(case, variant_q, suffix_id=f"x{loop:02d}-{idx:02d}", session_id=case.get("session_id")))
                    if len(expanded) >= target_min:
                        break
                if len(expanded) >= target_min:
                    break

    return expanded


def write_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "question",
                "case_type",
                "session_id",
                "expected_route",
                "actual_route",
                "expected_category",
                "actual_category",
                "expected_source_id",
                "actual_source_id",
                "elapsed_ms",
                "passed",
                "error",
                "reason",
            ]
        )
        for row in report["results"]:
            writer.writerow(
                [
                    row["id"],
                    row["question"],
                    row["case_type"],
                    row["session_id"],
                    row["expected_route"],
                    row["actual_route"],
                    row["expected_category"],
                    row["actual_category"],
                    row.get("expected_source_id"),
                    row.get("actual_source_id"),
                    row["elapsed_ms"],
                    row["passed"],
                    row["error"] or "",
                    " | ".join(row.get("reasons") or []),
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run >=1000-question regression suite for UPH chatbot")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="")
    parser.add_argument("--csv-output", default="")
    parser.add_argument("--cases-output", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--target-min", type=int, default=1000)
    parser.add_argument("--retry", type=int, default=1)
    args = parser.parse_args()

    base_cases = reg100.build_full_test_set()
    cases = expand_base_cases(base_cases, args.target_min)
    if args.limit > 0:
        cases = cases[: args.limit]

    if args.cases_output:
        cases_path = Path(args.cases_output)
        cases_path.parent.mkdir(parents=True, exist_ok=True)
        with cases_path.open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"Running {len(cases)} test cases against {args.base_url}")
    print("=" * 60)

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']}: {case['question'][:60]}...", end=" ")
        session_id = case.get("session_id") or f"reg1000-{case['id']}"
        prev_results = [row for row in results if row.get("session_id") == session_id]

        attempt = 0
        result = None
        while attempt < args.retry + 1:
            result = reg100.run_test(args.base_url, case, session_id, prev_results)
            if result["passed"] or not result["error"]:
                break
            attempt += 1
        assert result is not None
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        if result["error"]:
            status = f"ERROR: {result['error'][:30]}"
        print(f"{status} ({result['elapsed_ms']}ms)")

    total = len(results)
    passed = sum(1 for row in results if row["passed"])
    failed = total - passed
    pass_rate = passed / total if total else 0.0
    avg_latency = sum(row["elapsed_ms"] for row in results) / total if total else 0
    max_latency = max((row["elapsed_ms"] for row in results), default=0)

    by_case_type: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_case_type.setdefault(row["case_type"], []).append(row)
    type_stats = {
        case_type: {
            "total": len(rows),
            "passed": sum(1 for row in rows if row["passed"]),
            "pass_rate": round(sum(1 for row in rows if row["passed"]) / len(rows), 4),
        }
        for case_type, rows in sorted(by_case_type.items())
    }

    report = {
        "timestamp": datetime.now().isoformat(),
        "base_url": args.base_url,
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(pass_rate, 4),
        "avg_latency_ms": int(avg_latency),
        "max_latency_ms": max_latency,
        "by_case_type": type_stats,
        "results": results,
    }

    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{total} passed ({round(pass_rate * 100, 1)}%)")
    print(f"Latency: avg={int(avg_latency)}ms, max={max_latency}ms")
    print("\nBy Case Type:")
    for case_type, stats in type_stats.items():
        print(f"  {case_type}: {stats['passed']}/{stats['total']} passed ({round(stats['pass_rate'] * 100, 1)}%)")

    failed_rows = [row for row in results if not row["passed"]]
    if failed_rows:
        print("\n" + "=" * 60)
        print("FAILED TESTS:")
        for row in failed_rows[:80]:
            print(f"  [{row['id']}] {row['question']}")
            if row["error"]:
                print(f"    Error: {row['error']}")
            else:
                for reason in row.get("reasons") or []:
                    print(f"    {reason}")

    output_path = Path(args.output) if args.output else None
    csv_path = Path(args.csv_output) if args.csv_output else None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {output_path}")
    if csv_path:
        write_csv(csv_path, report)
        print(f"CSV report written to: {csv_path}")

    return 0 if pass_rate >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
