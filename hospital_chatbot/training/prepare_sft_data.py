"""Prepare supervised fine-tuning data for UPH_ChatBot from knowledge.jsonl.

Input: knowledge.jsonl with category/question/answer records.
Output: JSONL records with `messages` suitable for chat SFT.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SYSTEM_PROMPT = (
    "คุณคือ UPH_ChatBot ผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยา "
    "ตอบเฉพาะข้อมูลบริการจากบริบทที่มี หากไม่พบข้อมูลให้แจ้งว่าไม่พบในระบบและแนะนำติดต่อเจ้าหน้าที่"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--knowledge', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    src = Path(args.knowledge)
    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in src.read_text(encoding='utf-8').splitlines() if line.strip()]
    with dst.open('w', encoding='utf-8') as f:
        for row in rows:
            question = str(row.get('question') or '').strip()
            answer = str(row.get('answer') or '').strip()
            category = str(row.get('category') or '').strip()
            if not question or not answer:
                continue
            example = {
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': question},
                    {'role': 'assistant', 'content': f'หมวด: {category}\n{answer}'},
                ]
            }
            f.write(json.dumps(example, ensure_ascii=False) + '\n')
    print(f'Wrote SFT data -> {dst}')


if __name__ == '__main__':
    main()
