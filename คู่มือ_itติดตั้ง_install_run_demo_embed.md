# คู่มือฝ่ายไอที: ติดตั้ง Ollama -> รัน demo -> ฝัง widget

## 1) สิ่งที่ต้องติดตั้ง
- Python 3.10+
- Node.js 18+
- Git
- Ollama
- (ถ้าจะ merge GGUF) llama.cpp บนเครื่อง build

## 2) โมเดลที่ต้อง pull
```cmd
ollama pull bge-m3:latest
ollama pull scb10x/typhoon2.5-qwen3-4b:latest
```

## 3) ถ้าจะสร้างชื่อโมเดลใช้งานเอง
- ใช้ `deployment/ollama/Modelfile.UPH_ChatBot.typhoon`
- หรือ merge GGUF แล้วใช้ `deployment/ollama/Modelfile.UPH_ChatBot.gguf`

## 4) ติดตั้ง demo stack บน Windows
ให้วางโปรเจกต์ที่ `D:\UPH_Chatbot\hospital_chatbot` และวาง KB ที่ `data\master_kb.xlsx`

จากนั้นรัน:
```cmd
scripts\v20_demo_stack_windows.cmd
```

สิ่งที่จะเกิดขึ้น:
- install Python deps
- install frontend deps
- build KB
- reindex Chroma
- เปิด backend ที่ `http://127.0.0.1:8000`
- เปิด frontend mockup ที่ `http://localhost:3000`

## 5) วิธีฝัง mockup chat บนเว็บ demo ของโรงพยาบาล
ไฟล์ที่ใช้:
- `frontend/widget_embed/chat-widget-loader.js`
- `frontend/widget_embed/embed_snippet.html`

ตำแหน่งที่ควรวาง:
- static assets ของเว็บโรงพยาบาล เช่น `/chatbot/widget_embed/`
- ใส่ snippet ก่อนปิด `</body>` ของหน้า demo/staging

## 6) สิ่งที่ห้ามทำ
- อย่าให้หน้าเว็บเรียก Ollama ตรง
- อย่าเปิดพอร์ต 11434 ออกภายนอก
- ถ้าแก้ Excel ต้อง build KB และ reindex ใหม่
- ถ้าเปลี่ยน embedding model ต้อง reindex ใหม่ทั้งหมด
