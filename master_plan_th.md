# Master Plan

เน้นทำให้โปรเจกต์พร้อม demo/staging และพร้อมส่งต่อทีมไอที/ทีมเว็บ โดยเพิ่ม 4 กลุ่มงานหลัก:

1. **Training data expansion จาก 38 verified rows**
   - เพิ่ม script `training/expand_sft_from_verified_kb.py`
   - ขยายคำถามเป็น formal / casual / typo / short / follow-up turns
   - ไม่เพิ่มข้อเท็จจริงใหม่จากภายนอก

2. **Fine-tune pipeline สำหรับเครื่องส่วนตัว RTX4050 6GB**
   - ปรับ `training/train_uph_chatbot_unsloth.py`
   - รองรับ local model cache/offline training บนไดรฟ์ D:
   - preload tokenizer ก่อน train เพื่อลดปัญหา network ระหว่างเริ่มเทรน

3. **Deployable demo / mockup stack**
   - เพิ่ม script `scripts/v20_demo_stack_windows.cmd`
   - เพิ่ม widget embed snippet สำหรับเว็บโรงพยาบาล
   - เพิ่มคู่มือว่าวาง widget ที่ไหนของหน้า demo

4. **Merge -> GGUF -> Ollama**
   - ใช้สคริปต์ `training/merge_lora_qwen25_3b.py`
   - แปลงและควอนไทซ์ (q8_0) โดยใช้ `convert_hf_to_gguf.py`
   - ใช้ชื่อโมเดล `uph_chatbot` (ตัวพิมพ์เล็กตามกฎ Ollama ล่าสุด)
   - ย้ายพื้นที่จัดเก็บ Ollama ไปที่ `D:\ollama_models` เพื่อแก้ปัญหาความจุเต็ม

## ข้อเสนอเชิงระบบ

- ให้ใช้ **RAG + topic tree + alias/typo router + human handoff** เป็นแกนหลัก
- fine-tune 3B ใช้เพื่อสไตล์ / ask-back / fallback / follow-up เท่านั้น
- อย่าให้ fine-tune กลายเป็น source of truth
- ใช้ log จริงจาก demo/staging เพื่อเพิ่ม verified KB ในรอบถัดไป
