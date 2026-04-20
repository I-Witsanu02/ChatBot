# Ollama deployment path for the fine-tuned hospital model

ลำดับ deploy ที่แนะนำ:

1. เทรนด้วย `Qwen/Qwen2.5-7B-Instruct`
2. ได้ LoRA adapter เช่น `up_hospital_lora/`
3. รัน `python scripts/merge_lora_qwen25.py`
4. รัน `bash scripts/export_gguf_qwen25.sh`
5. รัน `bash scripts/create_ollama_model.sh`
6. รัน `python scripts/verify_ollama_serving.py`
7. ตั้ง `OLLAMA_MODEL=up-hospital-qwen2.5-7b-instruct`
8. รัน backend

เหตุผลที่ใช้เส้นทางนี้:
- serving model จะอยู่บน base lineage เดียวกับที่ fine-tune จริง
- ลดความเสี่ยงใช้ Ollama model คนละสายโดยไม่ตั้งใจ
- rollback และ version control ง่ายขึ้น
