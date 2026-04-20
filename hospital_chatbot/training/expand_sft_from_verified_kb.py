"""Expand verified KB into many training turns without inventing new facts."""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = (
    "คุณคือ UPH_ChatBot ผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยา "
    "ตอบด้วยข้อมูลที่ได้รับอนุมัติจากโรงพยาบาลเท่านั้น หากไม่พบข้อมูลให้บอกว่าไม่พบในระบบและแนะนำติดต่อเจ้าหน้าที่"
)
FOLLOWUPS = ["ราคาเท่าไหร่", "ติดต่อที่ไหน", "เปิดวันไหน", "เข้าได้เลยไหม", "ใช้สิทธิอะไรได้บ้าง"]
TYPO_MAP = {
    "วัคซีน": ["วักซีน", "วัปซีน", "วคซีน", "วัดซีน"],
    "แพทย์": ["แพทยื", "เเพทย์", "เเพทยื"],
    "ตรวจ": ["ตรจ", "ตรวด"],
    "บริจาค": ["บริจา่ค", "บรจาค"],
    "สูตินรีเวช": ["kmsรีเวช", "สูคินรีเวช"],
}
CATEGORY_ALIASES = {
    "การจัดการนัดหมาย": ["นัด", "เลื่อนนัด", "จองคิว", "ต่อคิว"],
    "ตารางแพทย์และเวลาทำการ": ["ตารางแพทย์", "ตารางหมอ", "หมอ", "แพทย์"],
    "คลินิกทันตกรรม": ["หมอฟัน", "ทันตกรรม", "ฟัน", "ทำฟัน"],
    "ศูนย์ไตเทียม": ["ฟอกไต", "ล้างไต", "ไตเทียม", "ศูนย์ไต"],
    "สูตินรีเวช": ["สูติ", "นรีเวช", "ฝากครรภ์", "ตรวจภายใน"],
    "ประเมินค่าใช้จ่ายทั่วไป": ["ค่าใช้จ่าย", "สิทธิการรักษา", "ย้ายสิทธิ", "เวชระเบียน", "สิทธิ"],
    "วัคซีน": ["วัคซีน", "วักซีน", "ฉีดวัคซีน"],
    "สวัสดิการวัคซีนนักศึกษา": ["วัคซีนสำหรับนักศึกษา", "วัคซีนนักศึกษา", "สิทธิวัคซีนนักศึกษา"],
    "ธนาคารเลือดและบริจาคเลือด": ["เลือด", "บริจาคเลือด", "ธนาคารเลือด"],
    "กลุ่มงานบุคคล": ["สมัครงาน", "บุคคล", "hr"],
    "ตรวจสุขภาพรายบุคคล": ["ตรวจสุขภาพ", "เช็กสุขภาพ", "แพ็กเกจตรวจสุขภาพ"],
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่า": ["ตรวจสุขภาพองค์กร", "เบิกจ่าย", "ตรวจสุขภาพบริษัท"],
    "การขอเอกสารทางการแพทย์": ["ใบรับรองแพทย์", "ขอเอกสาร", "เวชระเบียน"],
}
FORMAL_PREFIXES = ["ขอสอบถาม", "รบกวนสอบถาม", "ต้องการสอบถาม", "ขอทราบ"]
CASUAL_PREFIXES = ["ขอถาม", "ถามหน่อย", "อยากรู้", "ขอข้อมูล"]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def typo_variants(text: str) -> list[str]:
    out = []
    for good, bads in TYPO_MAP.items():
        if good in text:
            for bad in bads:
                out.append(text.replace(good, bad))
    return out


def short_question_variants(row: dict[str, Any]) -> list[str]:
    category = str(row.get('category') or '').strip()
    question = str(row.get('question') or '').strip()
    variants = list(CATEGORY_ALIASES.get(category, []))
    for token in re.split(r"[()\/,-]", question):
        token = normalize(token)
        if 3 <= len(token) <= 25 and not token.startswith('สามารถ'):
            variants.append(token)
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out[:10]


def paraphrases(question: str) -> list[str]:
    q = normalize(question)
    outs = [q]
    outs.extend(f"{p}{q}" for p in FORMAL_PREFIXES)
    outs.extend(f"{p} {q}" for p in CASUAL_PREFIXES)
    if 'ราคาเท่าไหร่' in q:
        outs.append(q.replace('ราคาเท่าไหร่', 'ราคาเท่าไร'))
    if 'เข้ามาได้เลยไหม' in q:
        outs.append(q.replace('เข้ามาได้เลยไหม', 'เข้าได้เลยไหม'))
    return outs


def build_examples_from_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    question = str(row.get('question') or '').strip()
    answer = str(row.get('answer') or '').strip()
    category = str(row.get('category') or '').strip()
    if not question or not answer:
        return []
    assistant = f"หมวด: {category}\n{answer}"
    user_questions = set(paraphrases(question))
    user_questions.update(short_question_variants(row))
    user_questions.update(typo_variants(question))
    examples: list[dict[str, Any]] = []
    for uq in list(user_questions):
        uq = normalize(uq)
        if not uq:
            continue
        examples.append({'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': uq},
            {'role': 'assistant', 'content': assistant},
        ]})
        for f in FOLLOWUPS[:3]:
            examples.append({'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': uq},
                {'role': 'assistant', 'content': assistant},
                {'role': 'user', 'content': f},
                {'role': 'assistant', 'content': assistant},
            ]})
    return examples


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--knowledge', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--target-min', type=int, default=300)
    ap.add_argument('--seed', type=int, default=3407)
    args = ap.parse_args()
    random.seed(args.seed)
    rows = [json.loads(x) for x in Path(args.knowledge).read_text(encoding='utf-8').splitlines() if x.strip()]
    examples: list[dict[str, Any]] = []
    for row in rows:
        examples.extend(build_examples_from_row(row))
    uniq = {json.dumps(ex['messages'], ensure_ascii=False): ex for ex in examples}
    examples = list(uniq.values())
    if len(examples) < args.target_min and examples:
        base = list(examples)
        while len(examples) < args.target_min:
            random.shuffle(base)
            examples.extend(base[: min(len(base), args.target_min - len(examples))])
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + '\n')
    print(f'Expanded {len(rows)} verified KB rows into {len(examples)} SFT turns -> {out}')


if __name__ == '__main__':
    main()
