from __future__ import annotations
import argparse
from pathlib import Path
from transformers import AutoTokenizer, AutoModelForCausalLM

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-name', required=True)
    ap.add_argument('--cache-dir', default=None)
    ap.add_argument('--output-dir', required=True)
    args = ap.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True, cache_dir=args.cache_dir)
    tok.save_pretrained(out)
    model = AutoModelForCausalLM.from_pretrained(args.model_name, trust_remote_code=True, cache_dir=args.cache_dir)
    model.save_pretrained(out)
    print(f'Preloaded model + tokenizer -> {out}')

if __name__ == '__main__':
    main()
