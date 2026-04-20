#!/usr/bin/env python3
"""Generate broader regression test sets from the KB.

V15 expands coverage for:
- alias / synonym routing
- typo handling
- broad category guidance
- gibberish / unreadable input fallback
- common follow-up style queries
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

DEFAULT_KNOWLEDGE = "knowledge.jsonl"
DEFAULT_OUTPUT = "regression_test_set_realistic.jsonl"
SEED = 3407

OUT_OF_SCOPE_QUERIES = [
    "ช่วยวินิจฉัยอาการให้หน่อย",
    "ควรกินยาอะไรเมื่อเป็นไข้",
    "มะเร็งรักษาหายไหม",
    "ผื่นแบบนี้อันตรายไหม",
    "ตั้งครรภ์กินยานี้ได้ไหม",
]

GIBBERISH_QUERIES = ["ฟหก", "กฟก", "sb;]", ";yd:uo", "asdfg"]

POLITE_PREFIXES = ["ขอสอบถาม", "รบกวนสอบถาม", "อยากทราบ", "ขอถามหน่อย"]
COLLOQUIAL_PATTERNS = [
    "{question} ได้มั้ย",
    "{question} ยังไงครับ",
    "{category} {question}",
    "ถ้าจะ{question}ต้องทำยังไง",
]
TYPO_MAP = {
    "นัด": "นัฐ",
    "วัคซีน": "วักซีน",
    "สิทธิ": "สิทธิ์",
    "รักษา": "รักสา",
    "ค่าใช้จ่าย": "ค่าไช้จ่าย",
    "แพทย์": "แพทยื",
}
TIME_SENSITIVE_KEYWORDS = ["ราคา", "ค่าใช้จ่าย", "วัคซีน", "ตารางแพทย์", "เวลาทำการ", "นัด"]
CATEGORY_ALIAS_CASES = {
    "การจัดการนัดหมาย": ["เลื่อนนัด", "จองคิว", "พบหมอ"],
    "ตารางแพทย์และเวลาทำการ": ["ตารางแพทย์", "หมอ", "แพทย์"],
    "คลินิกทันตกรรม": ["หมอฟัน", "ทำฟัน", "ปวดฟัน"],
    "ศูนย์ไตเทียม": ["ฟอกไต", "ไตเทียม"],
    "สูตินรีเวช": ["ฝากครรภ์", "ตรวจภายใน"],
    "ประเมินค่าใช้จ่ายทั่วไป": ["สิทธิการรักษา", "ย้ายสิทธิ"],
    "วัคซีน": ["วัก", "ฉีดวัคซีน"],
    "สวัสดิการวัคซีนนักศึกษา": ["วัคซีนสำหรับนักศึกษา", "วัคซีนนักศึกษา"],
    "ค่าใช้จ่าย": ["บริจาคเลือด", "ธนาคารเลือด", "เลือด"],
    "กลุ่มงานบุคคล": ["สมัครงาน", "รับสมัครงาน"],
    "ตรวจสุขภาพรายบุคคล": ["ตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ"],
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่า": ["ตรวจสุขภาพองค์กร", "เบิกจ่าย"],
    "การขอเอกสารทางการแพทย์": ["ใบรับรองแพทย์", "ขอเวชระเบียน"],
}
FOLLOW_UP_CASES = ["ราคาเท่าไหร่", "ติดต่อที่ไหน", "เปิดวันไหน", "เข้าได้เลยไหม", "มีไหม"]


def load_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def add_typos(text: str) -> str:
    out = text
    for good, wrong in TYPO_MAP.items():
        if good in out:
            out = out.replace(good, wrong, 1)
            break
    return out


def needs_time_sensitive_case(record: dict[str, Any]) -> bool:
    hay = " ".join([str(record.get("category") or ""), str(record.get("question") or "")])
    return any(k in hay for k in TIME_SENSITIVE_KEYWORDS)


def make_cases(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    random.seed(SEED)
    rows: list[dict[str, Any]] = []
    seen_categories: set[str] = set()

    for rec in records:
        q = rec["question"]
        category = rec["category"]
        rid = rec["id"]
        rows.append({"id": f"exact::{rid}", "question": q, "expected_route": "answer", "expected_source_id": rid, "expected_category": category, "case_type": "exact"})
        rows.append({"id": f"polite::{rid}", "question": f"{random.choice(POLITE_PREFIXES)}{q}", "expected_route": "answer", "expected_source_id": rid, "expected_category": category, "case_type": "polite_paraphrase"})
        rows.append({"id": f"colloquial::{rid}", "question": random.choice(COLLOQUIAL_PATTERNS).format(question=q, category=category), "expected_route": "answer", "expected_source_id": rid, "expected_category": category, "case_type": "colloquial"})
        rows.append({"id": f"typo::{rid}", "question": add_typos(q), "expected_route": "answer", "expected_source_id": rid, "expected_category": category, "case_type": "typo"})
        if needs_time_sensitive_case(rec):
            rows.append({"id": f"time::{rid}", "question": f"ตอนนี้{q}", "expected_route": "answer", "expected_source_id": rid, "expected_category": category, "case_type": "time_sensitive"})
        if category not in seen_categories:
            seen_categories.add(category)
            rows.append({"id": f"broad::{category}", "question": f"อยากถามเรื่อง{category}", "expected_route": "clarify", "expected_source_id": None, "expected_category": category, "case_type": "broad_ambiguous"})
            for idx, alias in enumerate(CATEGORY_ALIAS_CASES.get(category, []), start=1):
                rows.append({"id": f"alias::{category}::{idx}", "question": alias, "expected_route": "clarify", "expected_source_id": None, "expected_category": category, "case_type": "category_alias"})

    # strong explicit cases
    rows.extend([
        {"id": "topic::student_vaccine", "question": "วัคซีนสำหรับนักศึกษา", "expected_route": "clarify", "expected_source_id": None, "expected_category": "สวัสดิการวัคซีนนักศึกษา", "case_type": "topic_alias"},
        {"id": "topic::blood_bank", "question": "เลือด", "expected_route": "clarify", "expected_source_id": None, "expected_category": "ค่าใช้จ่าย", "case_type": "topic_alias"},
        {"id": "topic::doctor", "question": "หมอ", "expected_route": "clarify", "expected_source_id": None, "expected_category": "ตารางแพทย์และเวลาทำการ", "case_type": "topic_alias"},
    ])

    for idx, q in enumerate(FOLLOW_UP_CASES, start=1):
        rows.append({"id": f"followup::{idx}", "question": q, "expected_route": "answer_or_clarify", "expected_source_id": None, "expected_category": None, "case_type": "follow_up"})

    for idx, q in enumerate(GIBBERISH_QUERIES, start=1):
        rows.append({"id": f"gibberish::{idx}", "question": q, "expected_route": "fallback", "expected_source_id": None, "expected_category": None, "case_type": "gibberish"})

    for idx, q in enumerate(OUT_OF_SCOPE_QUERIES, start=1):
        rows.append({"id": f"oos::{idx}", "question": q, "expected_route": "fallback", "expected_source_id": None, "expected_category": None, "case_type": "out_of_scope"})
    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate realistic regression test set")
    p.add_argument("--knowledge", default=DEFAULT_KNOWLEDGE)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    records = load_records(Path(args.knowledge))
    rows = make_cases(records)
    write_jsonl(Path(args.output), rows)
    print(f"Wrote {len(rows)} cases to {args.output}")


if __name__ == "__main__":
    main()
