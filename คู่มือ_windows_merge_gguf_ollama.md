# Windows CMD: Merge -> GGUF -> Modelfile -> Ollama

## สมมติ path
- โปรเจกต์: `D:\UPH_chatbot\hospital_chatbot`
- LoRA adapter: `artifacts\uph_chatbot_lora_3b_final`
- llama.cpp: `D:\llama.cpp`

## 1) merge
```cmd
call .venv-train\Scripts\activate.bat
python training\merge_lora_qwen25_3b.py --base-model Qwen/Qwen2.5-3B-Instruct --adapter-dir artifacts\uph_chatbot_lora_3b_final --output-dir artifacts\uph_chatbot_merged_3b --cache-dir D:\hf_cache
```

## 2) export GGUF
```cmd
python D:\llama.cpp\convert_hf_to_gguf.py artifacts\uph_chatbot_merged_3b --outfile artifacts\uph_chatbot_merged_3b_gguf\uph_chatbot_3b_f16.gguf
```

## 3) quantize
```cmd
D:\llama.cpp\llama-quantize.exe artifacts\uph_chatbot_merged_3b_gguf\uph_chatbot_3b_f16.gguf artifacts\uph_chatbot_merged_3b_gguf\uph_chatbot_3b_q4_k_m.gguf q4_k_m
```

## 4) สร้าง Modelfile
ใช้ `deployment/ollama/Modelfile.UPH_ChatBot.gguf`
และแก้บรรทัด `FROM` ให้ชี้ไปที่ไฟล์ GGUF จริง

## 5) create model ใน Ollama
```cmd
cd artifacts\uph_chatbot_merged_3b_gguf
ollama create UPH_ChatBot -f Modelfile
ollama run UPH_ChatBot
```

## 6) ทดสอบระบบกับ backend
```cmd
set OLLAMA_MODEL=UPH_ChatBot
python -m uvicorn backend.app:app --reload --port 8000
```
