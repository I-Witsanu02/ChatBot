# review / test notes

สิ่งที่ทดสอบใน environment นี้ผ่านแล้ว (เสร็จสมบูรณ์ 100%):
- ✅ py_compile ของ scripts/training ใหม่
- ✅ pytest ของ `tests/test_expand_sft.py`
- ✅ รัน `expand_sft_from_verified_kb.py` ได้จำนวน output มากกว่า 2,300+ turns
- ✅ Next.js frontend ทำงานปกติบน `localhost:3000` (เอาปุ่มย้อนกลับ/หน้าหลัก/คัดลอกออกแล้ว)
- ✅ API Backend รันเสถียรบน `localhost:8001` (ป้องกัน Port 8000 ชน)
- ✅ โมเดล Typo จับคำผิดได้อย่างแม่นยำ ("ตรจสุขภาพ", "วัปซีน", "abcdef" Fallback อย่างเหมาะสม)
- ✅ Unsloth full training run 1 epoch เสร็จสมบูรณ์
- ✅ Merge / GGUF (q8_0) รันเสร็จสมบูรณ์
- ✅ Ollama runtime ดึง `uph_chatbot` ไปเก็บไว้ใน `D:\ollama_models` สำเร็จ
