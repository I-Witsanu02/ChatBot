#!/usr/bin/env python3
"""Build structured KB artifacts from the canonical hospital Excel workbook."""

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

DEFAULT_INPUT = "data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx"
DEFAULT_JSONL = "data/knowledge.jsonl"
DEFAULT_CSV = "data/knowledge.csv"
DEFAULT_REPORT = "data/kb_validation_report.json"
DEFAULT_MANIFEST = "data/kb_manifest.json"

APPOINTMENT_MENU = "นัดหมายและตารางแพทย์"
VACCINE_MENU = "วัคซีนและบริการผู้ป่วยนอก"
RIGHTS_MENU = "เวชระเบียน สิทธิ และค่าใช้จ่าย"
HEALTH_CHECK_MENU = "ตรวจสุขภาพและใบรับรองแพทย์"
CONTACT_MENU = "ติดต่อหน่วยงานเฉพาะและสมัครงาน"

MAIN_MENU_TREE: dict[str, list[str]] = {
    APPOINTMENT_MENU: [
        "ขอเลื่อนนัดพบแพทย์",
        "ลืมวันนัด / เช็ควันนัด",
        "ตารางแพทย์ออกตรวจ",
        "เวลาทำการแผนกผู้ป่วยนอก",
    ],
    VACCINE_MENU: [
        "วัคซีนบาดทะยัก/พิษสุนัขบ้า",
        "วัคซีนไวรัสตับอักเสบบี",
        "วัคซีนไข้หวัดใหญ่",
        "วัคซีน HPV",
    ],
    RIGHTS_MENU: [
        "ย้ายสิทธิการรักษา / ตรวจสอบสิทธิ",
        "ขอประวัติการรักษา",
        "ค่าใช้จ่ายในการรักษา",
    ],
    HEALTH_CHECK_MENU: [
        "โปรแกรมตรวจสุขภาพ",
        "เวลาตรวจสุขภาพ",
        "ตรวจสุขภาพหมู่คณะ / หน่วยงาน",
        "ใช้สิทธิเบิกตรงตรวจสุขภาพได้ไหม",
        "ขอใบรับรองแพทย์",
    ],
    CONTACT_MENU: [
        "หน่วยไตเทียม",
        "ธนาคารเลือด / บริจาคเลือด",
        "โรงพยาบาลทันตกรรม",
        "สมัครงาน / งานบุคคล",
    ],
}

SPECIALTY_ALIAS_MAP: dict[str, list[str]] = {
    "กระดูกและข้อ": ["กระดูก", "ศัลยกรรมกระดูก", "ออร์โธ", "ortho"],
    "กุมารแพทย์": ["กุมาร", "เด็ก", "หมอเด็ก"],
    "ตา": ["จักษุ", "หมอตา"],
    "ทางเดินปัสสาวะ": ["ระบบทางเดินปัสสาวะ", "ยูโร", "urology"],
    "ผิวหนัง": ["คลินิกผิวหนัง", "หมอผิวหนัง", "โรคผิวหนัง"],
    "รังสีวินิจฉัย": ["เอ็กซเรย์", "xray", "x-ray", "ct", "ซีที"],
    "สูติ-นรีเวช": ["สูติ", "นรีเวช", "สูตินรีเวช", "ฝากครรภ์"],
    "หูคอจมูก": ["ent", "หูคอจมูก"],
    "อายุรกรรม 1": ["อายุรกรรม", "med", "อายุรกรรม 1"],
    "อายุรกรรม 2": ["อายุรกรรม", "med", "อายุรกรรม 2"],
    "เวชศาสตร์": ["เวชศาสตร์", "gp", "ทั่วไป"],
}

MENU_ALIAS_HINTS: dict[str, list[str]] = {
    APPOINTMENT_MENU: ["นัดหมาย", "ตารางแพทย์", "เลื่อนนัด", "วันนัด", "opd", "หมอ", "แพทย์"],
    VACCINE_MENU: ["วัคซีน", "วักซีน", "วคซีน", "hpv", "ไข้หวัดใหญ่", "บาดทะยัก", "พิษสุนัขบ้า"],
    RIGHTS_MENU: ["เวชระเบียน", "สิทธิ", "สิทธิการรักษา", "ค่าใช้จ่าย", "ค่ารักษา", "ขอประวัติ"],
    HEALTH_CHECK_MENU: ["ตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "ใบรับรองแพทย์", "check up", "check-up"],
    CONTACT_MENU: ["ไตเทียม", "ฟอกไต", "บริจาคเลือด", "ธนาคารเลือด", "ทันตกรรม", "หมอฟัน", "สมัครงาน", "บุคคล"],
}


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
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def normalize(text: str) -> str:
    text = clean_text(text).lower()
    text = re.sub(r"[^0-9a-zA-Zก-๙\s/@.-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    return normalize(text).replace(" ", "")


def slugify(text: str) -> str:
    text = normalize(text)
    text = re.sub(r"[^0-9a-zA-Zก-๙]+", "_", text)
    return text.strip("_") or "item"


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)>\]]+", clean_text(text))


def dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = clean_text(item)
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def split_attachment_field(value: str) -> list[str]:
    text = clean_text(value)
    if not text or text == "-":
        return []
    parts = re.split(r"[\n,|]+", text)
    return dedupe_preserve(parts)


def list_attachment_paths(folder: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not folder.exists():
        return mapping
    for item in folder.iterdir():
        if item.is_file():
            mapping[normalize(item.stem)] = str(item.resolve())
    return mapping


def extract_sentence_by_keywords(text: str, keywords: list[str]) -> str:
    raw = clean_text(text)
    if not raw:
        return ""
    chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+|\n+", raw) if c.strip()]
    for chunk in chunks:
        chunk_norm = normalize(chunk)
        if any(normalize(k) in chunk_norm for k in keywords):
            return chunk
    return ""


def extract_contact(text: str) -> str:
    phones = re.findall(r"(?:0\d[\d\s-]{6,}\d)(?:\s*ต่อ\s*\d+)?", clean_text(text))
    chunk = extract_sentence_by_keywords(text, ["โทร", "ติดต่อ", "line", "@"])
    values = dedupe_preserve([chunk, *phones])
    return "\n".join(values)


def extract_hours(text: str) -> str:
    hours = re.findall(r"(?:วัน[^\n,]*?|ทุกวัน[^\n,]*?)(?:\d{1,2}[.:]\d{2}\s*-\s*\d{1,2}[.:]\d{2}\s*น\.?|หยุด[^\n]*)", clean_text(text))
    chunk = extract_sentence_by_keywords(text, ["เวลา", "วันจันทร์", "วันอังคาร", "ทุกวัน", "เปิด"])
    values = dedupe_preserve([*hours, chunk])
    return "\n".join(values)


def extract_price(text: str) -> str:
    prices = re.findall(r"[^.\n]*\d[\d,]*(?:\.\d+)?\s*บาท[^.\n]*", clean_text(text))
    chunk = extract_sentence_by_keywords(text, ["ราคา", "บาท", "ค่าบริการ"])
    values = dedupe_preserve([*prices, chunk])
    return "\n".join(values)


def extract_walkin(text: str) -> str:
    return extract_sentence_by_keywords(
        text,
        ["เข้ามา", "walk in", "walk-in", "ประเมินอาการ", "ใช้สิทธิ", "สำรองจ่าย", "ทำหนังสือ", "ก่อนเท่านั้น"],
    )


def build_keyword_list(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in re.split(r"[\s,;:()\/\-]+", normalize(value)):
            if len(token) >= 2:
                tokens.append(token)
    return dedupe_preserve(tokens)[:40]


def default_child_topics(category: str) -> list[str]:
    return MAIN_MENU_TREE.get(category, [])


def infer_menu_and_child(sheet_name: str, question: str) -> tuple[str, str]:
    q = normalize(question)
    if sheet_name == "ตรวจสุขภาพ":
        if "หมู่คณะ" in q or "หน่วยงาน" in q:
            return HEALTH_CHECK_MENU, "ตรวจสุขภาพหมู่คณะ / หน่วยงาน"
        if "เบิกตรง" in q:
            return HEALTH_CHECK_MENU, "ใช้สิทธิเบิกตรงตรวจสุขภาพได้ไหม"
        if "ใบรับรองแพทย์" in q:
            return HEALTH_CHECK_MENU, "ขอใบรับรองแพทย์"
        if "วันไหน" in q or "เวลา" in q:
            return HEALTH_CHECK_MENU, "เวลาตรวจสุขภาพ"
        return HEALTH_CHECK_MENU, "โปรแกรมตรวจสุขภาพ"
    if sheet_name == "QA เวชระเบียน":
        if "ย้ายสิทธิ" in q or "ตรวจสอบสิทธิ" in q:
            return RIGHTS_MENU, "ย้ายสิทธิการรักษา / ตรวจสอบสิทธิ"
        if "ประวัติการรักษา" in q:
            return RIGHTS_MENU, "ขอประวัติการรักษา"
        return RIGHTS_MENU, "ค่าใช้จ่ายในการรักษา"
    if sheet_name == "QA ไตเทียม":
        return CONTACT_MENU, "หน่วยไตเทียม"
    if sheet_name == "QA ธนาคารเลือด":
        return CONTACT_MENU, "ธนาคารเลือด / บริจาคเลือด"
    if sheet_name == "QA ทันตกรรม":
        return CONTACT_MENU, "โรงพยาบาลทันตกรรม"
    if sheet_name == "QA งานบุคคล":
        return CONTACT_MENU, "สมัครงาน / งานบุคคล"
    if "ตารางแพทย์" in q or "แพทย์ออกตรวจ" in q or "หมอ" in q:
        return APPOINTMENT_MENU, "ตารางแพทย์ออกตรวจ"
    if "เลื่อนนัด" in q:
        return APPOINTMENT_MENU, "ขอเลื่อนนัดพบแพทย์"
    if "ลืมวันนัด" in q or "เช็ควันนัด" in q or "ใบนัดหาย" in q:
        return APPOINTMENT_MENU, "ลืมวันนัด / เช็ควันนัด"
    if "เวลาทำการ" in q or "เปิดกี่โมง" in q:
        return APPOINTMENT_MENU, "เวลาทำการแผนกผู้ป่วยนอก"
    if "วัคซีน" in q:
        if "พิษสุนัขบ้า" in q or "บาดทะยัก" in q:
            return VACCINE_MENU, "วัคซีนบาดทะยัก/พิษสุนัขบ้า"
        if "ไวรัสตับอักเสบบี" in q:
            return VACCINE_MENU, "วัคซีนไวรัสตับอักเสบบี"
        if "ไข้หวัดใหญ่" in q:
            return VACCINE_MENU, "วัคซีนไข้หวัดใหญ่"
        if "hpv" in q:
            return VACCINE_MENU, "วัคซีน HPV"
        return VACCINE_MENU, "วัคซีนและบริการผู้ป่วยนอก"
    return CONTACT_MENU, "ติดต่อหน่วยงานเฉพาะและสมัครงาน"


def attachment_match_paths(raw_names: list[str], directory_map: dict[str, str]) -> list[str]:
    out: list[str] = []
    for name in raw_names:
        key = normalize(Path(name).stem)
        matched = directory_map.get(key)
        if matched:
            out.append(matched)
    return dedupe_preserve(out)


def infer_health_check_images(question: str, note: str, image_map: dict[str, str]) -> list[str]:
    q = normalize(f"{question} {note}")
    out: list[str] = []
    if "โปรแกรมตรวจสุขภาพ" in q or "ตรวจสุขภาพ" in q:
        for key, path in image_map.items():
            if "โปรแกรมตรวจสุขภาพ" in key:
                out.append(path)
    if "line" in q or "ไลน์" in q or "qr" in q or "check up" in q:
        for key, path in image_map.items():
            if "ไลน์ check up" in key or "ไลน์" in key:
                out.append(path)
    return dedupe_preserve(out)


def infer_specialty_image(specialty: str, image_map: dict[str, str]) -> list[str]:
    spec_norm = normalize(specialty)
    hits: list[str] = []
    for key, path in image_map.items():
        if key == spec_norm or key in spec_norm or spec_norm in key:
            hits.append(path)
    alias_hits = [image_map[k] for alias in SPECIALTY_ALIAS_MAP.get(specialty, []) for k in image_map if normalize(alias) in k]
    return dedupe_preserve(hits + alias_hits)


def make_aliases(question: str, child_topic: str, category: str, extra: list[str] | None = None) -> list[str]:
    bits = [question, child_topic, category, *(extra or []), *MENU_ALIAS_HINTS.get(category, [])]
    aliases = dedupe_preserve(bits + build_keyword_list(question, child_topic))
    return aliases[:40]


def record_base(
    *,
    record_id: str,
    source_sheet: str,
    source_row: int,
    category: str,
    subcategory: str,
    topic: str,
    question: str,
    answer: str,
    note: str,
    aliases: list[str],
    keywords: list[str],
    followup_contact: str = "",
    followup_hours: str = "",
    followup_price: str = "",
    followup_walkin: str = "",
    followup_link: str = "",
    followup_image_paths: list[str] | None = None,
    department: str | None = None,
    record_type: str = "faq_leaf",
    source_priority: int = 50,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "source_sheet": source_sheet,
        "source_row": source_row,
        "category": category,
        "subcategory": subcategory,
        "topic": topic,
        "question": question,
        "answer": answer,
        "note": note,
        "notes": note,
        "keywords": keywords,
        "aliases": aliases,
        "followup_price": followup_price,
        "followup_contact": followup_contact,
        "followup_hours": followup_hours,
        "followup_walkin": followup_walkin,
        "followup_link": followup_link,
        "followup_image_paths": followup_image_paths or [],
        "effective_from": extra.pop("effective_from", ""),
        "updated_at": now_bangkok_iso(),
        "last_updated_at": now_bangkok_iso(),
        "department": department,
        "contact": followup_contact or department or "",
        "status": "active",
        "record_type": record_type,
        "source_priority": source_priority,
        **extra,
    }


def build_faq_records(
    workbook_path: Path,
    schedule_image_map: dict[str, str],
    health_image_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    workbook = pd.ExcelFile(workbook_path)
    issues: list[ValidationIssue] = []
    records: list[dict[str, Any]] = []

    for sheet_name in workbook.sheet_names:
        if sheet_name == "แพทย์ออกตรวจ OPD":
            continue
        df = pd.read_excel(workbook_path, sheet_name=sheet_name).fillna("")
        for idx, row in df.iterrows():
            row_number = idx + 2
            question = clean_text(row.get("คำถามยอดฮิต") or row.get("คำถาม"))
            answer = clean_text(row.get("คำตอบ"))
            note = clean_text(row.get("หมายเหตุ"))
            if not question or not answer:
                issues.append(ValidationIssue("warning", sheet_name, row_number, "question", "Skipped row with missing question/answer"))
                continue

            category, child_topic = infer_menu_and_child(sheet_name, question)
            link_values = dedupe_preserve(extract_urls(f"{answer}\n{note}"))
            followup_link = "\n".join(link_values)
            attachment_names = split_attachment_field(clean_text(row.get("ไฟล์แนบ/พาธรูป")))
            image_paths = attachment_match_paths(attachment_names, schedule_image_map)
            if sheet_name == "ตรวจสุขภาพ":
                image_paths = dedupe_preserve(image_paths + infer_health_check_images(question, note, health_image_map))

            record_type = "faq_leaf"
            source_priority = 90
            if sheet_name == "Total QA" and "ตารางแพทย์" in normalize(question):
                record_type = "guidance"
                source_priority = 20

            text_bundle = "\n".join([answer, note])
            record = record_base(
                record_id=f"qa-{len(records)+1:04d}",
                source_sheet=sheet_name,
                source_row=row_number,
                category=category,
                subcategory=child_topic,
                topic=child_topic,
                question=question,
                answer=answer,
                note=note,
                aliases=make_aliases(question, child_topic, category),
                keywords=build_keyword_list(question, answer, note, child_topic),
                followup_contact=extract_contact(text_bundle),
                followup_hours=extract_hours(text_bundle),
                followup_price=extract_price(text_bundle),
                followup_walkin=extract_walkin(text_bundle),
                followup_link=followup_link,
                followup_image_paths=image_paths,
                record_type=record_type,
                source_priority=source_priority,
                source_name=sheet_name,
            )
            records.append(record)
    return records, issues


def build_schedule_records(workbook_path: Path, schedule_image_map: dict[str, str]) -> list[dict[str, Any]]:
    df = pd.read_excel(workbook_path, sheet_name="แพทย์ออกตรวจ OPD").fillna("")
    records: list[dict[str, Any]] = []
    current_department = ""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}

    for idx, row in df.iterrows():
        department = clean_text(row.get("แผนก")) or current_department
        specialty = clean_text(row.get("เฉพาะทาง"))
        day = clean_text(row.get("วันออกตรวจ"))
        hours = clean_text(row.get("เวลา"))
        doctor = clean_text(row.get("รายชื่อแพทย์ออกตรวจ"))
        if department:
            current_department = department
        specialty = specialty or "ทั่วไป"
        key = (department, specialty)
        grouped.setdefault(key, [])
        grouped[key].append(
            {
                "day": day,
                "hours": hours,
                "doctor": doctor,
                "row_number": str(idx + 2),
            }
        )

    counter = 1
    for (department, specialty), items in grouped.items():
        lines = []
        row_numbers = []
        for item in items:
            row_numbers.append(item["row_number"])
            lines.append(f"- {item['day']} {item['hours']} : {item['doctor']}".strip())
        answer = f"{specialty} ({department})\n" + "\n".join(lines)
        question = f"ตารางแพทย์ {specialty}"
        aliases = make_aliases(
            question,
            "ตารางแพทย์ออกตรวจ",
            APPOINTMENT_MENU,
            extra=[specialty, department, *SPECIALTY_ALIAS_MAP.get(specialty, [])],
        )
        record = record_base(
            record_id=f"schedule-{counter:03d}",
            source_sheet="แพทย์ออกตรวจ OPD",
            source_row=int(row_numbers[0]),
            category=APPOINTMENT_MENU,
            subcategory="ตารางแพทย์ออกตรวจ",
            topic=specialty,
            question=question,
            answer=answer,
            note=f"แผนก {department}",
            aliases=aliases,
            keywords=build_keyword_list(question, specialty, department, answer),
            followup_contact="",
            followup_hours="\n".join(dedupe_preserve([f"{x['day']} {x['hours']}".strip() for x in items])),
            followup_link="",
            followup_image_paths=infer_specialty_image(specialty, schedule_image_map),
            department=department,
            record_type="schedule_specific",
            source_priority=120,
            specialty=specialty,
            clinic=department,
        )
        records.append(record)
        counter += 1
    return records


def add_menu_nodes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(records)
    existing_ids = {r["id"] for r in out}
    for menu, children in MAIN_MENU_TREE.items():
        menu_id = f"menu-{slugify(menu)}"
        if menu_id not in existing_ids:
            out.append(
                record_base(
                    record_id=menu_id,
                    source_sheet="__menu__",
                    source_row=0,
                    category=menu,
                    subcategory="",
                    topic=menu,
                    question=menu,
                    answer="\n".join(f"- {item}" for item in children),
                    note="เมนูนำทางหลัก",
                    aliases=make_aliases(menu, "", menu),
                    keywords=build_keyword_list(menu, *children),
                    record_type="menu_node",
                    source_priority=5,
                    child_topics=children,
                )
            )
        for child in children:
            child_id = f"child-{slugify(menu)}-{slugify(child)}"
            if child_id in existing_ids:
                continue
            child_records = [r for r in records if r.get("category") == menu and r.get("subcategory") == child]
            answer = "\n".join(f"- {r['question']}" for r in child_records[:8]) or "เลือกหัวข้อย่อยที่ต้องการสอบถาม"
            out.append(
                record_base(
                    record_id=child_id,
                    source_sheet="__menu__",
                    source_row=0,
                    category=menu,
                    subcategory=child,
                    topic=child,
                    question=child,
                    answer=answer,
                    note="เมนูย่อย",
                    aliases=make_aliases(child, child, menu),
                    keywords=build_keyword_list(menu, child, answer),
                    record_type="child_topic",
                    source_priority=10,
                    child_questions=[r["question"] for r in child_records[:8]],
                )
            )
            existing_ids.add(child_id)
    return out


def validate_records(records: list[dict[str, Any]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_questions: set[tuple[str, str]] = set()
    for record in records:
        question = clean_text(record.get("question"))
        answer = clean_text(record.get("answer"))
        category = clean_text(record.get("category"))
        source_sheet = clean_text(record.get("source_sheet"))
        source_row = int(record.get("source_row") or 0)
        if not category:
            issues.append(ValidationIssue("error", source_sheet, source_row, "category", "Missing category"))
        if not question:
            issues.append(ValidationIssue("error", source_sheet, source_row, "question", "Missing question"))
        if not answer:
            issues.append(ValidationIssue("warning", source_sheet, source_row, "answer", "Missing answer text"))
        key = (category.lower(), question.lower())
        if key in seen_questions and record.get("record_type") not in {"menu_node", "child_topic"}:
            issues.append(ValidationIssue("warning", source_sheet, source_row, "question", "Duplicate question within category"))
        seen_questions.add(key)
    return issues


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for record in records for key in record.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = dict(record)
            for key, value in list(row.items()):
                if isinstance(value, list):
                    row[key] = " | ".join(str(v) for v in value)
            writer.writerow(row)


def write_report(path: Path, issues: list[ValidationIssue], record_count: int) -> None:
    payload = {
        "record_count": record_count,
        "issue_count": len(issues),
        "issues": [issue.as_dict() for issue in issues],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build structured KB from the canonical UPH workbook")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--jsonl-output", default=DEFAULT_JSONL)
    parser.add_argument("--csv-output", default=DEFAULT_CSV)
    parser.add_argument("--report-output", default=DEFAULT_REPORT)
    parser.add_argument("--manifest-output", default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workbook_path = Path(args.input)
    jsonl_path = Path(args.jsonl_output)
    csv_path = Path(args.csv_output)
    report_path = Path(args.report_output)
    manifest_path = Path(args.manifest_output)

    schedule_image_map = list_attachment_paths(PROJECT_ROOT / "data" / "ตารางออกตรวจแพทย์")
    health_image_map = list_attachment_paths(PROJECT_ROOT / "data" / "ตรวจสุขภาพประจำปี")

    faq_records, issues = build_faq_records(workbook_path, schedule_image_map, health_image_map)
    schedule_records = build_schedule_records(workbook_path, schedule_image_map)
    records = add_menu_nodes(faq_records + schedule_records)
    records.sort(
        key=lambda r: (
            str(r.get("category", "")),
            str(r.get("subcategory", "")),
            -int(r.get("source_priority", 0)),
            str(r.get("question", "")),
        )
    )

    issues.extend(validate_records(records))

    write_jsonl(jsonl_path, records)
    write_csv(csv_path, records)
    write_report(report_path, issues, len(records))

    manifest = build_manifest(
        source_workbook=workbook_path,
        knowledge_jsonl=jsonl_path,
        records=records,
        validation_issue_count=len(issues),
    )
    save_manifest(manifest_path, manifest)
    print(f"Wrote {len(records)} records from {workbook_path.name} -> {jsonl_path}")


if __name__ == "__main__":
    main()
