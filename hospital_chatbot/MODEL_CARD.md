# Model Card: UPH Hospital Chatbot (Revised)

## 1. Model/System Details

### Project Name
UPH Hospital Chatbot / น้องฟ้ามุ่ย AI

### System Type
Verified KB-first / RAG-first hospital service chatbot

### Main Components
- Frontend: Next.js
- Backend: FastAPI
- LLM Runtime: Ollama
- Knowledge Base: `data/knowledge.jsonl`, `data/knowledge.csv`
- Main Excel Source: `data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx`
- Attachments: schedule and health-check images under `data/`

### Important Design Choice
ระบบนี้ไม่ใช่ LLM-only และไม่ควรให้ LLM เป็นแหล่งความจริงของข้อมูลโรงพยาบาล  
ข้อมูลจริง เช่น เบอร์โทร ตารางแพทย์ เวลาให้บริการ ราคา และรูปภาพ ต้องมาจาก KB หรือ structured source ที่ตรวจสอบแล้ว

---

## 2. Intended Use

เหมาะสำหรับ:
- ข้อมูลบริการโรงพยาบาล
- ตารางแพทย์และเวลาทำการ
- วัคซีนและบริการผู้ป่วยนอก
- ตรวจสุขภาพและใบรับรองแพทย์
- ช่องทางติดต่อและเลขต่อ
- คำถามที่มีข้อมูลอยู่ในฐานความรู้

ไม่เหมาะสำหรับ:
- วินิจฉัยโรค
- ให้คำแนะนำการรักษาเฉพาะบุคคล
- วิเคราะห์อาการแทนแพทย์
- ใช้ในภาวะฉุกเฉิน
- รับหรือประมวลผลข้อมูลผู้ป่วยจริงโดยไม่ผ่านนโยบาย PDPA
- ตอบข้อมูลที่ไม่มีใน KB โดยการคาดเดา

---

## 3. Knowledge Base

### Primary Source
`data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx`

### Runtime Files
- `data/knowledge.jsonl`
- `data/knowledge.csv`

### Image Assets
- `data/ตารางออกตรวจแพทย์/`
- `data/ตรวจสุขภาพประจำปี/`

### Update Workflow
1. แก้ข้อมูลใน Excel ต้นฉบับ
2. Rebuild/export เป็น `knowledge.jsonl` และ `knowledge.csv`
3. ตรวจว่าไม่มีคอลัมน์หมายเหตุหลุดในคำตอบผู้ใช้
4. Restart backend
5. รัน regression/UAT

---

## 4. Model Behavior

### KB-first Behavior
ระบบพยายามตอบจาก:
1. menu/routing logic
2. structured schedule master
3. health-check shortcut
4. knowledge retrieval
5. safe fallback

### LLM Role
LLM ใช้เป็นตัวช่วยสำหรับ:
- ทำความเข้าใจคำถาม
- ช่วยเรียบเรียงคำตอบ
- รองรับคำถามภาษาธรรมชาติ
- ช่วยกรณีที่ retrieval มี context ที่ชัดเจน

LLM ไม่ควร:
- แต่งเบอร์โทร
- แต่งราคา
- แต่งตารางแพทย์
- ตอบคำแนะนำทางการแพทย์
- ใช้ข้อมูลที่ไม่มีแหล่งอ้างอิงใน KB

---

## 5. Safety Policy

ระบบควรปฏิเสธหรือ fallback เมื่อ:
- คำถามไม่มีข้อมูลในฐานความรู้
- คำถามต้องการวินิจฉัยโรค
- คำถามต้องการคำแนะนำการรักษาเฉพาะบุคคล
- คำถามเกี่ยวกับราคาหรือบริการที่ไม่มีข้อมูลยืนยัน
- retrieval confidence ต่ำ

ข้อความ fallback ควรแนะนำให้ติดต่อโรงพยาบาลโดยใช้เบอร์กลาง:
`0 5446 6666 ต่อ 7000`

---

## 6. Privacy and Data Handling

- ฐานความรู้ที่ส่งมอบไม่ควรมีข้อมูลผู้ป่วยจริง
- ไม่ควร commit `.env`, logs, analytics DB หรือ audit logs
- หากเปิด logging ใน production ต้องมีนโยบาย retention/anonymization
- การทดสอบ UAT ควรใช้คำถามสมมติ ไม่ใช้ข้อมูลผู้ป่วยจริง

---

## 7. Evaluation Plan

ควรวัดผลหลายระดับ:

| Metric | Purpose |
|---|---|
| Focused Regression Pass Rate | ตรวจเคสสำคัญที่ต้องไม่พัง |
| Intent Accuracy | วัดการจับเจตนาคำถาม |
| Retrieval Hit@1 / Hit@3 | วัดว่าดึง KB ถูกไหม |
| Faithfulness | ตรวจว่าคำตอบยึดตาม context |
| Answer Relevancy | ตรวจว่าตอบตรงคำถาม |
| Hallucination Rate | วัดการแต่งข้อมูล |
| Fallback Accuracy | วัดว่าคำถามนอก KB fallback ถูกไหม |
| Attachment Accuracy | รูปที่แนบตรงกับคำตอบไหม |
| Schedule Completeness | ตารางแพทย์ครบไหม |
| Doctor Alias Match Rate | ค้นชื่อแพทย์/ชื่อย่อได้ไหม |
| Forbidden Leakage Rate | มี `D:\`, `หมายเหตุ:`, `อัปเดตล่าสุด:` หลุดไหม |
| Latency p50/p95 | วัดความเร็วตอบ |
| Human UAT Score | ความพึงพอใจและความถูกต้องจากผู้ทดสอบ |

---

## 8. Known Limitations

- ความถูกต้องขึ้นกับความถูกต้องของ KB
- ตารางแพทย์และราคาบริการเปลี่ยนได้ ต้องอัปเดตฐานความรู้
- ถ้าไม่มี KB โมเดลไม่ควรถือว่าตอบข้อมูลโรงพยาบาลได้ถูกต้อง
- การรองรับชื่อเล่น/คำสะกดผิดต้องพัฒนา alias/fuzzy matching เพิ่ม
- ถ้ามีผู้ใช้พร้อมกันจำนวนมาก อาจต้องปรับ deployment และ model serving

---

## 9. Recommended Model Improvement

ควรทำใน experimental branch เท่านั้น ไม่แก้ production ทันที

แนะนำ:
- Hybrid Retrieval: Dense Embedding + BM25 + Entity Score
- Cross-Encoder Reranking
- Thai Entity Alias Matching
- Confidence-based Fallback
- Answer Verifier
- Active Learning จากคำถามที่ fallback
- Targeted LoRA/QLoRA เฉพาะ intent/query rewrite/safe style
- RAGAS และ BERTScore evaluation
- Ablation study เปรียบเทียบ LLM-only, RAG-only, RAG+rerank, final KB-first system

ไม่แนะนำ:
- เทรนให้โมเดลจำข้อมูลโรงพยาบาลทั้งหมด
- เอาข้อมูลผิด/คำตอบเก่า/หมายเหตุ/log ผู้ใช้จริงเข้า training
- ฝังตารางแพทย์หรือข้อมูลที่เปลี่ยนบ่อยลงใน model weight

---

## 10. Deployment Requirements

Recommended:
- Python 3.11
- Node.js LTS
- Ollama
- Backend port 8000
- Frontend port 3000
- HTTPS/reverse proxy for production
- Monitoring and log policy

Model files such as `.gguf` should be transferred separately and should not be committed to GitHub.

---

## 11. Compliance Notes

ระบบนี้เป็น information chatbot ไม่ใช่อุปกรณ์แพทย์ และไม่ควรใช้แทนการประเมินโดยบุคลากรทางการแพทย์  
หากนำไปใช้จริงต้องพิจารณา PDPA, data retention, access control, audit log policy และการตรวจข้อมูลโดยเจ้าของข้อมูลของโรงพยาบาล
