# สิ่งที่ต้องส่งให้โรงพยาบาล

## ก้อนที่ 1: Demo package
- code โปรเจกต์ทั้งหมด
- mockup/staging URL (Next.js รันที่ port 3000)
- widget embed files

## ก้อนที่ 2: KB package
- data/master_kb.xlsx
- data/knowledge.jsonl
- kb_manifest.json
- kb_validation_report.json

## ก้อนที่ 3: Model package
- โมเดลพื้นฐาน/สำรอง: ใช้ `scb10x/typhoon2.5-qwen3-4b` สำหรับทดสอบกรณีเริ่มต้น
- ตัวไฟน์จูนของโรงพยาบาล: `uph_chatbot` (สร้างจาก q8_0 GGUF ของ Qwen2.5-3B-Instruct + LoRA)
  - หมายเหตุ: โมเดลรันจากไดรฟ์ D: (OLLAMA_MODELS=D:\ollama_models) เพื่อประหยัดพื้นที่ไดรฟ์ C:

## ก้อนที่ 4: Runtime package
- backend (รันบน port 8001 เพื่อป้องกัน Port Conflict)
- frontend/mockup
- scripts
- requirements.txt

## ก้อนที่ 5: Test & review package
- regression test set
- ผล benchmark เปรียบเทียบ Typhoon vs uph_chatbot
- รายการสิ่งที่ระบบทำได้ / ทำไม่ได้ (รองรับ Typo ตัวอักษรผิดและ Alias เต็มรูปแบบ)

## ก้อนที่ 6: IT handoff package
- คำสั่งติดตั้ง (คู่มือ IT)
- คำสั่งรัน
- วิธี update KB
- วิธี rollback
- วิธีดู request logs / handoff queue
