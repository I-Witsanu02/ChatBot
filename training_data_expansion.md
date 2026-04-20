# คู่มือขยาย training turns จาก 38 verified rows

## หลักคิด

มีคำตอบยืนยันจากโรงพยาบาล 38 ข้อ ห้ามเติมข้อเท็จจริงจากอินเทอร์เน็ตตรง ๆ แต่สามารถขยาย **รูปแบบคำถาม** ได้จำนวนมาก

สิ่งที่ script `training/expand_sft_from_verified_kb.py` ทำ:
- formal variants
- casual variants
- short queries
- typo variants
- follow-up templates
- category aliases

คำสั่ง:

```cmd
python training\expand_sft_from_verified_kb.py --knowledge data\knowledge.jsonl --output data\uph_chatbot_sft_expanded.jsonl --target-min 500
```

ผลลัพธ์:
- จาก 38 verified rows จะได้ประมาณ 300-800 turns ตาม target และความหลากหลายของหมวด
- คำตอบยังยึด answer เดิมจากโรงพยาบาล

## วิธีใช้
1. build KB ก่อน
2. ขยาย SFT turns
3. train 3B test model
4. merge/GGUF/Ollama
5. benchmark เทียบกับ Typhoon เดิม
