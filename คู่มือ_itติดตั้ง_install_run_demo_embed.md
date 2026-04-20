# คู่มือฝ่ายไอที: ติดตั้ง Ollama -> รัน demo -> ฝัง widget

## 1) สิ่งที่ต้องติดตั้ง
- Python 3.10+
- Node.js 18+
- Git
- Ollama
- (ถ้าจะ merge GGUF) ต้องมี llama.cpp บนเครื่อง build

## 2) กำหนดพื้นที่จัดเก็บโมเดลป้องกันสโตเรจเต็ม
ตั้งค่า Environment Variables ไว้ระดับระบบของเซิร์ฟเวอร์
```cmd
setx OLLAMA_MODELS "D:\ollama_models"
setx HF_HOME "D:\hf_cache"
```
*(ถ้าเผลอเปิด Ollama ไว้ ให้ปิดและเปิด Service Ollama ใหม่อีกครั้งเพื่อเริ่มใช้ Path ใหม่)*

## 3) โมเดลที่ต้อง pull / สร้าง
```cmd
ollama pull bge-m3:latest
ollama pull scb10x/typhoon2.5-qwen3-4b:latest
```
- ถ้าจะสร้างชื่อโมเดลใช้งานด้วยตัวไฟล์ GGUF ของโรงพยาบาล ให้ใช้ชื่อ **`uph_chatbot`** (ตัวพิมพ์เล็กเท่านั้นเนื่องจากกฎเวอร์ชันใหม่ของ Ollama) และรันด้วยคำสั่ง `ollama create uph_chatbot -f Modelfile`

## 4) ติดตั้ง demo stack บน Windows
ให้วางโปรเจกต์ที่ `D:\UPH_chatbot\hospital_chatbot` และวาง KB ที่ `data\master_kb.xlsx`

จากนั้นรัน:
```cmd
scripts\v20_demo_stack_windows.cmd
```

สิ่งที่จะเกิดขึ้น:
- install Python deps
- install frontend deps
- build KB
- reindex Chroma
- เปิด backend ที่ `http://127.0.0.1:8001` (หลีกเลี่ยง Port 8000 ที่อาจจะชนกับระบบอื่น)
- เปิด frontend mockup ที่ `http://localhost:3000`

## 5) วิธีฝัง mockup chat บนเว็บ demo ของโรงพยาบาล
ไฟล์ที่ใช้:
- `frontend/widget_embed/chat-widget-loader.js`
- `frontend/widget_embed/embed_snippet.html`

ตำแหน่งที่ควรวาง:
- static assets ของเว็บโรงพยาบาล เช่น `/chatbot/widget_embed/`
- ใส่ snippet ก่อนปิด `</body>` ของหน้า demo/staging

## 6) สิ่งที่ห้ามทำ
-อย่าให้หน้าเว็บเรียก Ollama ตรง 
-อย่าเปิดพอร์ต 11434 ออกภายนอก
-ถ้าแก้ Excel ต้อง build KB และ reindex ใหม่
-ถ้าเปลี่ยน embedding model ต้อง reindex ใหม่ทั้งหมด
