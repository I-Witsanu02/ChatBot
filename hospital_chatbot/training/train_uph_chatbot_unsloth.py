"""Train UPH_ChatBot LoRA on a small personal GPU (RTX 4050 6GB friendly).

V20 improvements:
- local model dir / offline cache support
- tokenizer preloading before Unsloth model load
- safer defaults for 3B on small GPUs
- optional max-steps quick test
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

# IMPORTANT: Unsloth first
import unsloth
from unsloth import FastLanguageModel

import torch
from datasets import Dataset
from transformers import AutoTokenizer, TrainingArguments
from trl import SFTTrainer

DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_MAX_SEQ = 1024
DEFAULT_BATCH = 1
DEFAULT_GRAD_ACCUM = 8
DEFAULT_EPOCHS = 2
DEFAULT_LR = 1e-4
DEFAULT_LORA_R = 8
DEFAULT_SAVE_STEPS = 50

SYSTEM_NOTE = (
    "This training config is optimized for a personal RTX 4050 Laptop GPU (~6GB VRAM). "
    "It prioritizes stability and successful test runs over raw quality."
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train UPH_ChatBot LoRA with Unsloth on a small GPU")
    p.add_argument("--model-name", default=DEFAULT_MODEL)
    p.add_argument("--local-model-dir", default=None, help="Optional local HF model dir for offline training")
    p.add_argument("--hf-cache-dir", default=None, help="Optional cache directory for HF/Transformers")
    p.add_argument("--train-file", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--max-seq-length", type=int, default=DEFAULT_MAX_SEQ)
    p.add_argument("--per-device-train-batch-size", type=int, default=DEFAULT_BATCH)
    p.add_argument("--gradient-accumulation-steps", type=int, default=DEFAULT_GRAD_ACCUM)
    p.add_argument("--num-train-epochs", type=int, default=DEFAULT_EPOCHS)
    p.add_argument("--learning-rate", type=float, default=DEFAULT_LR)
    p.add_argument("--lora-r", type=int, default=DEFAULT_LORA_R)
    p.add_argument("--save-steps", type=int, default=DEFAULT_SAVE_STEPS)
    p.add_argument("--max-steps", type=int, default=-1)
    p.add_argument("--logging-steps", type=int, default=5)
    p.add_argument("--seed", type=int, default=3407)
    p.add_argument("--load-in-4bit", action="store_true", default=True)
    p.add_argument("--no-load-in-4bit", dest="load_in_4bit", action="store_false")
    return p.parse_args()


def is_bf16_supported() -> bool:
    return bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())


def load_messages_jsonl(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def format_messages_to_text(example: dict[str, Any], tokenizer) -> str:
    messages = example.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return ""
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)


def build_text_dataset(train_file: str, tokenizer) -> Dataset:
    rows = load_messages_jsonl(train_file)
    texts = []
    for row in rows:
        text = format_messages_to_text(row, tokenizer)
        if text.strip():
            texts.append({"text": text})
    if not texts:
        raise ValueError("No valid training texts were generated from the input file.")
    return Dataset.from_list(texts)


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not found. This script is intended for a GPU machine.")

    bf16 = is_bf16_supported()
    fp16 = not bf16
    model_source = args.local_model_dir or args.model_name
    local_only = bool(args.local_model_dir)

    print("=" * 88)
    print("UPH_ChatBot local training (RTX 4050 friendly config)")
    print(SYSTEM_NOTE)
    print(f"Base model                : {args.model_name}")
    print(f"Model source              : {model_source}")
    print(f"Train file                : {args.train_file}")
    print(f"Output dir                : {args.output_dir}")
    print(f"Max seq length            : {args.max_seq_length}")
    print(f"Batch size                : {args.per_device_train_batch_size}")
    print(f"Grad accumulation         : {args.gradient_accumulation_steps}")
    print(f"Epochs                    : {args.num_train_epochs}")
    print(f"Learning rate             : {args.learning_rate}")
    print(f"LoRA rank                 : {args.lora_r}")
    print(f"Save steps                : {args.save_steps}")
    print(f"Max steps                 : {args.max_steps}")
    print(f"Use 4-bit                 : {args.load_in_4bit}")
    print(f"bf16 supported            : {bf16}")
    print("=" * 88)

    tokenizer = AutoTokenizer.from_pretrained(
        model_source,
        trust_remote_code=True,
        use_fast=True,
        cache_dir=args.hf_cache_dir,
        local_files_only=local_only,
    )

    model, _ = FastLanguageModel.from_pretrained(
        model_name=model_source,
        max_seq_length=args.max_seq_length,
        dtype=torch.bfloat16 if bf16 else torch.float16,
        load_in_4bit=args.load_in_4bit,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=max(16, args.lora_r * 2),
        lora_dropout=0.0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    dataset = build_text_dataset(args.train_file, tokenizer)
    print(f"Loaded training rows       : {len(dataset)}")

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        num_train_epochs=args.num_train_epochs,
        max_steps=args.max_steps,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        bf16=bf16,
        fp16=fp16,
        optim="adamw_8bit",
        lr_scheduler_type="cosine",
        warmup_steps=max(1, int(0.03 * max(10, len(dataset)))),
        weight_decay=0.01,
        report_to="none",
        save_total_limit=2,
        seed=args.seed,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        packing=False,
        args=training_args,
    )

    #trainer.train(resume_from_checkpoint=True)
    trainer.train()
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"✅ Saved LoRA adapter -> {args.output_dir}")


if __name__ == "__main__":
    main()
