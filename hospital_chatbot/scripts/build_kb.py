#!/usr/bin/env python3
"""Build structured KB artifacts from the hospital Excel workbook.

Outputs:
- knowledge.jsonl
- knowledge.csv
- kb_validation_report.json
- kb_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.versioning import build_manifest, now_bangkok_iso, save_manifest

DEFAULT_INPUT = "จัดกลุ่มคำถาม.xlsx"
DEFAULT_JSONL = "knowledge.jsonl"
DEFAULT_CSV = "knowledge.csv"
DEFAULT_REPORT = "kb_validation_report.json"
DEFAULT_MANIFEST = "kb_manifest.json"


@dataclass(slots=True)
class ValidationIssue:
    level: str
    sheet: str
    row_number: int
    field: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "sheet": self.sheet,
            "row_number": self.row_number,
            "field": self.field,
            "message": self.message,
        }


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    text = clean_text(text).lower()
    text = re.sub(r"[^0-9a-zA-Zก-๙]+", "_", text)
    return text.strip("_") or "item"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "หัวข้อ": "subcategory",
        "หมวด": "category_override",
        "คำถามยอดฮิต": "question",
        "คำถามที่พบบ่อย": "question",
        "คำถาม": "question",
        "คำตอบ": "answer",
        "หมายเหตุ": "notes",
        "หน่วยงาน": "department",
        "แผนก": "department",
        "ติดต่อ": "contact",
        "เบอร์ติดต่อ": "contact",
        "สถานะ": "status",
        "เริ่มใช้": "effective_from",
        "สิ้นสุดการใช้": "effective_to",
        "ต้องถามกลับ": "requires_clarification",
    }
    return df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})


def parse_bool(value: Any) -> bool:
    value = clean_text(value).lower()
    return value in {"1", "true", "yes", "y", "ใช่", "ต้อง", "required"}


def generate_keywords(question: str, answer: str = "") -> list[str]:
    combined = clean_text(f"{question} {answer}").lower()
    tokens = re.split(r"[\s,;:()\[\]{}\/\\\-]+", combined)
    tokens = [t for t in tokens if len(t) >= 2]
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out[:24]


def validate_record(record: dict[str, Any], sheet: str, row_number: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not record["question"]:
        issues.append(ValidationIssue("error", sheet, row_number, "question", "Missing question"))
    if not record["answer"]:
        issues.append(ValidationIssue("error", sheet, row_number, "answer", "Missing answer"))
    if record["status"] not in {"active", "inactive"}:
        issues.append(ValidationIssue("warning", sheet, row_number, "status", "Unknown status; defaulted to active"))
        record["status"] = "active"
    return issues


def build_records(excel_path: Path) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    workbook = pd.ExcelFile(excel_path)
    records: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    used_ids: set[str] = set()

    for sheet_name in workbook.sheet_names:
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        df = normalize_columns(df)
        for idx, row in df.iterrows():
            row_number = idx + 2
            category = clean_text(row.get("category_override")) or clean_text(sheet_name)
            subcategory = clean_text(row.get("subcategory"))
            if subcategory.isdigit():
                subcategory = ""
            question = clean_text(row.get("question"))
            answer = clean_text(row.get("answer"))
            notes = clean_text(row.get("notes"))
            department = clean_text(row.get("department")) or None
            contact = clean_text(row.get("contact")) or None
            status = clean_text(row.get("status")).lower() or "active"
            effective_from = clean_text(row.get("effective_from")) or None
            effective_to = clean_text(row.get("effective_to")) or None
            requires_clarification = parse_bool(row.get("requires_clarification"))

            base_id = slugify(f"{category}_{subcategory or idx + 1}")
            candidate_id = base_id
            suffix = 1
            while candidate_id in used_ids:
                suffix += 1
                candidate_id = f"{base_id}_{suffix}"
            used_ids.add(candidate_id)

            record = {
                "id": candidate_id,
                "category": category,
                "subcategory": subcategory,
                "question": question,
                "answer": answer,
                "keywords": generate_keywords(question, answer),
                "notes": notes,
                "department": department,
                "contact": contact,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "last_updated_at": now_bangkok_iso(),
                "status": status,
                "requires_clarification": requires_clarification,
                "source_sheet": sheet_name,
                "source_row": row_number,
            }
            row_issues = validate_record(record, sheet_name, row_number)
            issues.extend(row_issues)
            if any(i.level == "error" for i in row_issues):
                continue
            records.append(record)
    return records, issues


def deduplicate_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (record["category"].strip().lower(), record["question"].strip().lower())
        if key in seen:
            issues.append(
                ValidationIssue(
                    "warning",
                    record["source_sheet"],
                    int(record["source_row"]),
                    "question",
                    f"Duplicate within category; kept first record {seen[key]['id']}",
                )
            )
            continue
        seen[key] = record
        deduped.append(record)
    return deduped, issues


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(records[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = {**rec, "keywords": "|".join(rec.get("keywords", []))}
            writer.writerow(row)


def write_report(path: Path, issues: list[ValidationIssue], record_count: int) -> None:
    payload = {
        "record_count": record_count,
        "issue_count": len(issues),
        "issues": [i.as_dict() for i in issues],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build hospital KB artifacts from Excel workbook")
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--jsonl-output", default=DEFAULT_JSONL)
    p.add_argument("--csv-output", default=DEFAULT_CSV)
    p.add_argument("--report-output", default=DEFAULT_REPORT)
    p.add_argument("--manifest-output", default=DEFAULT_MANIFEST)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    excel_path = Path(args.input)
    jsonl_path = Path(args.jsonl_output)
    csv_path = Path(args.csv_output)
    report_path = Path(args.report_output)
    manifest_path = Path(args.manifest_output)

    records, issues = build_records(excel_path)
    records, dedupe_issues = deduplicate_records(records)
    issues.extend(dedupe_issues)

    write_jsonl(jsonl_path, records)
    write_csv(csv_path, records)
    write_report(report_path, issues, len(records))
    manifest = build_manifest(
        source_workbook=excel_path,
        knowledge_jsonl=jsonl_path,
        records=records,
        validation_issue_count=len(issues),
    )
    save_manifest(manifest_path, manifest)
    print(f"Wrote {len(records)} records -> {jsonl_path}")


if __name__ == "__main__":
    main()
