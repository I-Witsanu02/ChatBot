"""Merge a Qwen2.5 LoRA adapter into the base model."""
from __future__ import annotations

import argparse
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-model', default='Qwen/Qwen2.5-7B-Instruct')
    parser.add_argument('--adapter-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(args.base_model, trust_remote_code=True, torch_dtype='auto')
    model = PeftModel.from_pretrained(base, args.adapter_dir)
    merged = model.merge_and_unload()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(out)
    tokenizer.save_pretrained(out)
    print(f'Merged model saved to {out}')


if __name__ == '__main__':
    main()
