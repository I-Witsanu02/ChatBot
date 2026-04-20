import os
import shutil
from huggingface_hub import snapshot_download

print("--- Fixing Qwen2.5 Tokenizer Bug ---")
# ดึงไฟล์พจนานุกรมต้นฉบับจาก Cache
src_dir = snapshot_download(repo_id="Qwen/Qwen2.5-3B-Instruct", allow_patterns=["tokenizer*.json", "vocab.json", "merges.txt"])
dest_dir = "artifacts/uph_chatbot_merged_3b_test"

# วางทับไฟล์ที่พัง
for file in ["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]:
    src_file = os.path.join(src_dir, file)
    dest_file = os.path.join(dest_dir, file)
    if os.path.exists(src_file):
        shutil.copy(src_file, dest_file)
        print(f"Fixed: {file}")

print("✅ Tokenizer successfully restored!")