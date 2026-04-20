from unsloth import FastLanguageModel
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-name", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--adapter-dir", required=True)
    ap.add_argument("--output-name", required=True)
    args = ap.parse_args()

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = args.model_name,
        max_seq_length = 2048,
        dtype = None,
        load_in_4bit = False,
    )
    
    # Load LoRA weights
    model.load_adapter(args.adapter_dir)
    
    # Save to GGUF q4_k_m
    model.save_pretrained_gguf(f"artifacts/{args.output_name}", tokenizer, quantization_method="q4_k_m")
    print(f"Exported GGUF successfully to artifacts/{args.output_name}")

if __name__ == "__main__":
    main()
