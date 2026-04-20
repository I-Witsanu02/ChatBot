# สิ่งที่ต้องส่งให้โรงพยาบาล

## ก้อนที่ 1: Demo package
- code โปรเจกต์ทั้งหมด
- mockup/staging URL
- widget embed files

## ก้อนที่ 2: KB package
- data/master_kb.xlsx
- data/knowledge.jsonl
- kb_manifest.json
- kb_validation_report.json

## ก้อนที่ 3: Model package
- ถ้าใช้ Typhoon ชั่วคราว: Modelfile + ชื่อโมเดล
- ถ้าใช้รุ่นของเรา: GGUF + Modelfile + model lock

## ก้อนที่ 4: Runtime package
- backend
- frontend/mockup
- scripts
- requirements.txt

## ก้อนที่ 5: Test & review package
- regression test set
- ผล benchmark เปรียบเทียบ Typhoon vs UPH_ChatBot-3B-test
- รายการสิ่งที่ระบบทำได้ / ทำไม่ได้

## ก้อนที่ 6: IT handoff package
- คำสั่งติดตั้ง
- คำสั่งรัน
- วิธี update KB
- วิธี rollback
- วิธีดู request logs / handoff queue
