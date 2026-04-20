from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_expand_sft_script(tmp_path: Path):
    kb = tmp_path / 'knowledge.jsonl'
    kb.write_text(
        json.dumps({
            'category': 'วัคซีน',
            'question': 'วัคซีนไวรัสตับอักเสบบี (ราคาเท่าไหร่/เข้ามาได้เลยไหม)',
            'answer': 'เข็มละ 260 บาท',
        }, ensure_ascii=False) + '\n',
        encoding='utf-8'
    )
    out = tmp_path / 'sft.jsonl'
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(root / 'training' / 'expand_sft_from_verified_kb.py'), '--knowledge', str(kb), '--output', str(out), '--target-min', '20']
    subprocess.run(cmd, check=True)
    rows = [json.loads(x) for x in out.read_text(encoding='utf-8').splitlines() if x.strip()]
    assert len(rows) >= 20
    joined = '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows)
    assert 'วักซีน' in joined or 'วัปซีน' in joined
    assert 'ราคาเท่าไหร่' in joined
