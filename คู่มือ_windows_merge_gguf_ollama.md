# Windows CMD: Merge -> GGUF -> Modelfile -> Ollama

## สมมติ path
- โปรเจกต์: `D:\UPH_chatbot\hospital_chatbot`
- LoRA adapter: `artifacts\uph_chatbot_lora_3b_final`
- llama.cpp: `D:\llama.cpp`

## 0) ย้ายพื้นที่จัดเก็บแคชเพื่อแก้ปัญหา Drive C เต็ม
เปิด Command Prompt / PowerShell แบบ Administrator แล้วรัน:
```cmd
setx OLLAMA_MODELS "D:\ollama_models"
setx HF_HOME "D:\hf_cache"
```
*(ถ้ารันเซิฟเวอร์ Ollama ค้างไว้อยู่ ให้ Restart Ollama ทิ้งหนึ่งครั้ง เพื่อให้รับทราบ Environment Variable ใหม่)*

## 1) merge
รันจากในโฟลเดอร์โปรเจกต์ `d:\UPH_chatbot\hospital_chatbot`
```cmd
$env:HF_HOME="D:\hf_cache"
.\.venv-train\Scripts\python.exe training\merge_lora_qwen25_3b.py --base-model Qwen/Qwen2.5-3B-Instruct --adapter-dir artifacts\uph_chatbot_lora_3b_final --output-dir artifacts\uph_chatbot_merged_3b --cache-dir D:\hf_cache
```

## 2) export GGUF (แบบ Quantized q8_0 ได้เลย ไม่ต้องใช้ llama-quantize.exe)
```cmd
$env:HF_HOME="D:\hf_cache"
.\.venv-train\Scripts\python.exe D:\llama.cpp\convert_hf_to_gguf.py artifacts\uph_chatbot_merged_3b --outfile artifacts\uph_chatbot_3b_q8_0.gguf --outtype q8_0
```

## 3) สร้าง Modelfile
ใช้ไฟล์ `D:\UPH_chatbot\Modelfile`
แน่ใจว่าบนหัวไฟล์มีบรรทัด `FROM` ชี้ไปที่ไฟล์ GGUF ในโปรเจกต์จริง เช่น:
`FROM ./hospital_chatbot/artifacts/uph_chatbot_3b_q8_0.gguf`

## 4) create model ใน Ollama
```cmd
cd D:\UPH_chatbot
$env:OLLAMA_MODELS="D:\ollama_models"
ollama create uph_chatbot -f Modelfile
ollama run uph_chatbot
```

## 5) ทดสอบระบบกับ backend
```cmd
cd D:\UPH_chatbot\hospital_chatbot
set OLLAMA_MODEL=uph_chatbot
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload --port 8001
```
