"""Knowledge-base versioning and stale-data utilities."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
VOLATILE_KEYWORDS = {
    "ราคา",
    "ค่าใช้จ่าย",
    "วัคซีน",
    "ตารางแพทย์",
    "เวลาทำการ",
    "นัดหมาย",
    "สิทธิ",
}
DEFAULT_STALE_DAYS = 30
VOLATILE_STALE_DAYS = 7


def now_bangkok_iso() -> str:
    return datetime.now(tz=BANGKOK_TZ).replace(microsecond=0).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BANGKOK_TZ)
        return dt.astimezone(BANGKOK_TZ)
    except ValueError:
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_jsonl_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def is_record_volatile(record: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(record.get("category") or ""),
            str(record.get("subcategory") or ""),
            str(record.get("question") or ""),
        ]
    )
    return any(keyword in haystack for keyword in VOLATILE_KEYWORDS)


def stale_days_for_record(record: dict[str, Any]) -> int:
    return VOLATILE_STALE_DAYS if is_record_volatile(record) else DEFAULT_STALE_DAYS


def is_record_stale(record: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or datetime.now(tz=BANGKOK_TZ)
    last_updated = parse_dt(record.get("last_updated_at"))
    if last_updated is None:
        return True
    return last_updated < now - timedelta(days=stale_days_for_record(record))


def compute_category_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        cat = str(rec.get("category") or "ไม่ระบุ")
        counts[cat] = counts.get(cat, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def stale_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    stale_records = [r for r in records if is_record_stale(r)]
    by_category: dict[str, int] = {}
    for rec in stale_records:
        cat = str(rec.get("category") or "ไม่ระบุ")
        by_category[cat] = by_category.get(cat, 0) + 1
    return {
        "stale_count": len(stale_records),
        "stale_ratio": round(len(stale_records) / len(records), 4) if records else 0.0,
        "by_category": dict(sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))),
        "sample_ids": [rec.get("id") for rec in stale_records[:10]],
    }


def build_manifest(
    *,
    source_workbook: Path | None,
    knowledge_jsonl: Path,
    records: list[dict[str, Any]],
    validation_issue_count: int,
) -> dict[str, Any]:
    workbook_hash = sha256_file(source_workbook) if source_workbook and source_workbook.exists() else None
    knowledge_hash = sha256_file(knowledge_jsonl) if knowledge_jsonl.exists() else None
    generated_at = now_bangkok_iso()
    version = generated_at.replace(":", "").replace("-", "")
    return {
        "kb_version": version,
        "generated_at": generated_at,
        "source_workbook": str(source_workbook) if source_workbook else None,
        "source_workbook_sha256": workbook_hash,
        "knowledge_jsonl": str(knowledge_jsonl),
        "knowledge_jsonl_sha256": knowledge_hash,
        "record_count": len(records),
        "validation_issue_count": validation_issue_count,
        "category_counts": compute_category_counts(records),
        "stale_summary": stale_summary(records),
    }


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
