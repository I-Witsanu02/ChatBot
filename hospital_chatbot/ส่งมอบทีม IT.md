# ส่งมอบทีม IT

## วัตถุประสงค์ของเอกสารนี้
เอกสารนี้ใช้สำหรับทีม IT ของโรงพยาบาล เพื่อเข้าใจว่า:
- ต้องรับไฟล์อะไรไปติดตั้ง
- ต้องเปิดระบบอย่างไร
- ห้ามอัปโหลดหรือส่งต่อไฟล์อะไร
- ฐานข้อมูลหลักอยู่ตรงไหน
- Frontend, Backend และ Knowledge Base เชื่อมกันอย่างไร

## โครงสร้างโฟลเดอร์ที่สำคัญ
```text
hospital_chatbot/
├─ backend/
├─ nextjs_frontend/
├─ data/
├─ scripts/
├─ requirements.txt
├─ test_focused_runtime_regression.py
├─ .env.example
├─ วิธีการใช้งาน.md
├─ ส่งมอบทีม IT.md
└─ UAT_CHECKLIST.md
```

## ไฟล์สำคัญที่ต้องใช้ในการ deploy
### Backend
- `backend/app.py`
- `backend/prompts.py`
- `backend/retrieval.py`
- `backend/rerank.py`
- `backend/policies.py`
- `backend/model_config.py`
- `backend/topic_tree.py`
- `backend/versioning.py`
- `backend/request_log.py`
- `backend/audit.py`
- `backend/handoff.py`

### Frontend
- `nextjs_frontend/app/page.js`
- `nextjs_frontend/app/layout.js`
- `nextjs_frontend/app/globals.css`
- `nextjs_frontend/app/error.js`
- `nextjs_frontend/package.json`
- `nextjs_frontend/package-lock.json`
- `nextjs_frontend/next.config.js`
- `nextjs_frontend/.env.example`

### Data
- `data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx`
- `data/knowledge.jsonl`
- `data/knowledge.csv`
- `data/kb_manifest.json`
- `data/ตารางออกตรวจแพทย์/`
- `data/ตรวจสุขภาพประจำปี/`

### Test และเอกสาร
- `test_focused_runtime_regression.py`
- `วิธีการใช้งาน.md`
- `ส่งมอบทีม IT.md`
- `UAT_CHECKLIST.md`

## ไฟล์ฐานข้อมูลหลักของระบบ
ต้นฉบับข้อมูลหลักคือ:

```text
data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx
```

ไฟล์ runtime ที่ระบบใช้ตอบจริงคือ:

```text
data/knowledge.jsonl
data/knowledge.csv
```

ข้อสำคัญ:
- ห้ามถือไฟล์ใน `data/ตารางออกตรวจแพทย์/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx` เป็นฐานข้อมูลหลัก
- โฟลเดอร์ `data/ตารางออกตรวจแพทย์/` มีไว้สำหรับรูปแนบตารางแพทย์

## Environment Variables ที่ควรรู้
ค่าหลักที่ใช้จริง:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=UP_FahMui_GGUF_q4
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TIMEOUT_SECONDS=30
ANSWER_MODE=kb_exact
RAG_GROUNDED_LLM=1
WORKBOOK_PATH=data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx
KNOWLEDGE_JSONL=data/knowledge.jsonl
KNOWLEDGE_CSV=data/knowledge.csv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_DEBUG_CHAT=0
```

## API Endpoints ที่เกี่ยวข้อง
### ใช้งานหน้าแชท
- `POST /chat`
- `POST /chat/reset-session`
- `GET /health`

### สำหรับงานดูแลระบบภายใน
- `GET /admin/status`
- `GET /admin/records`
- `GET /admin/audit`
- `GET /admin/request-logs`

หมายเหตุ:
- Admin endpoints ไม่ควรเปิดสู่สาธารณะโดยไม่มีการป้องกัน

## คำสั่ง Build Frontend
สำหรับพัฒนา:

```bat
cd /d D:\UPH_chatbot\hospital_chatbot\nextjs_frontend
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
set NEXT_PUBLIC_DEBUG_CHAT=0
npm run dev
```

สำหรับ production-like:

```bat
cd /d D:\UPH_chatbot\hospital_chatbot\nextjs_frontend
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
set NEXT_PUBLIC_DEBUG_CHAT=0
npm run build
npm run start
```

## ความต้องการของโมเดล
ถ้าจะรันแบบ offline:
- ต้องมี Ollama
- ต้องมีโมเดลที่ตั้งค่าใน `OLLAMA_MODEL`
- ต้องมีพื้นที่เก็บ model แยกจาก source code

ข้อสำคัญ:
- โมเดลไม่ใช่แหล่งข้อมูลหลักของโรงพยาบาล
- คำตอบจริงควรมาจาก Knowledge Base และไฟล์ข้อมูลที่ตรวจสอบแล้ว
- ไฟล์ `.gguf` ควรส่งมอบแยกต่างหาก ไม่ควร commit ขึ้น GitHub

## หมายเหตุด้านข้อมูลและความเป็นส่วนตัว
ระบบมีไฟล์ log ภายใน เช่น:
- `data/chatbot_analytics.db`
- `logs/audit.jsonl`

ถ้ามีข้อมูลผู้ใช้จริง:
- ต้องลบหรือ anonymize ก่อนส่งมอบ
- ห้ามส่ง log ที่มีข้อมูลส่วนบุคคลออกนอกหน่วยงาน

ห้ามทดสอบด้วย:
- ข้อมูลผู้ป่วยจริง
- ข้อมูลสุขภาพจริง
- รหัสประจำตัวประชาชน
- secret keys หรือ token ของระบบอื่น

## ไฟล์หรือโฟลเดอร์ที่ไม่ควรอัปโหลดหรือส่งต่อ
- `.venv/`
- `node_modules/`
- `.next/`
- `__pycache__/`
- `*.pyc`
- `.env`
- `logs/`
- `data/chatbot_analytics.db` ถ้ามีข้อมูลจริง
- `logs/audit.jsonl` ถ้ามีข้อมูลจริง
- ไฟล์โมเดล `.gguf`
- ไฟล์ `.safetensors`
- ไฟล์ `.bin`
- ข้อมูลผู้ป่วยจริง
- secret keys

## คำแนะนำสำหรับ Production Deployment
- ใช้ HTTPS เสมอ
- แยก Frontend และ Backend ให้ชัดเจน
- จำกัดสิทธิ์เข้าถึง admin endpoints
- แยก storage ของ model ออกจาก source code
- สำรองข้อมูล `data/knowledge.jsonl`, `data/knowledge.csv`, และรูปแนบ
- วางนโยบาย retention ของ log ให้สอดคล้องกับ PDPA
- ถ้าจะเปิดให้ใช้ภายในองค์กร ให้จำกัดการเข้าถึงเฉพาะเครือข่ายที่จำเป็น


แต่ต้องแจ้งให้ชัดว่า:
- Frontend อย่างเดียวเปิดหน้าเว็บได้
- ถ้าไม่มี Backend `/chat` ระบบจะไม่สามารถตอบคำถามได้
