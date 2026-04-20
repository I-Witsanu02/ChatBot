# review / test notes

สิ่งที่ทดสอบใน environment นี้:
- py_compile ของ scripts/training ใหม่
- pytest ของ `tests/test_expand_sft.py`
- รัน `expand_sft_from_verified_kb.py` กับ knowledge.jsonl จริงเพื่อดูจำนวน output

สิ่งที่ยังไม่ได้รันจริงใน environment นี้:
- Next.js production build/run
- Ollama runtime จริง
- merge/GGUF pipeline จริง
- full training run จริง
