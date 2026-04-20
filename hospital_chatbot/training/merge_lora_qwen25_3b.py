"""Merge a Qwen2.5-3B base model with a LoRA adapter for UPH_ChatBot."""
from __future__ import annotations
import argparse
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-model', default='Qwen/Qwen2.5-3B-Instruct')
    ap.add_argument('--adapter-dir', required=True)
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--cache-dir', default=None)
    args = ap.parse_args()
    base = AutoModelForCausalLM.from_pretrained(args.base_model, trust_remote_code=True, torch_dtype='auto', device_map='cpu', cache_dir=args.cache_dir)
    peft_model = PeftModel.from_pretrained(base, args.adapter_dir)
    merged = peft_model.merge_and_unload()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(out)
    tok = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True, cache_dir=args.cache_dir)
    tok.save_pretrained(out)
    print(f'Merged model -> {out}')

if __name__ == '__main__':
    main()
