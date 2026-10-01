"""
QLoRA / LoRA fine-tuning script for Qwen3-4B (or 8B) on the EPANET engineering dataset.

Usage (Linux + NVIDIA GPU, or CPU/macOS with reduced settings):
    python -m ai_module.training.train_qlora \
        --base-model Qwen/Qwen3-4B \
        --train-file ai_module/data/sft_datasets/train_qwen3_chatml.jsonl \
        --val-file ai_module/data/sft_datasets/val_qwen3_chatml.jsonl \
        --output-dir ai_module/training/checkpoints/qwen3-epanet-lora

Requirements:
    pip install torch transformers datasets peft trl accelerate bitsandbytes

Notes:
- 4-bit QLoRA keeps Qwen3-8B trainable on a single 16–24 GB VRAM GPU.
- On CPU, set --no-4bit and use --max-seq-length 2048 to avoid OOM.
- Only the assistant messages are supervised; system/user are masked.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from ai_module.config.settings import LORA_ADAPTER_PATH


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def to_hf_dataset(rows: List[Dict[str, Any]]) -> "Dataset":  # type: ignore
    from datasets import Dataset

    return Dataset.from_list(rows)


def build_text_with_masking(rows: List[Dict[str, Any]], tokenizer) -> List[Dict[str, Any]]:
    """
    Converts ChatML-style messages into tokenized text + label mask.
    Labels are -100 for system/user tokens so loss is only computed on assistant text.
    """
    out: List[Dict[str, Any]] = []
    for row in rows:
        messages = row["messages"]
        token_ids: List[int] = []
        labels: List[int] = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            encoded = tokenizer.apply_chat_template(
                [{"role": role, "content": content}],
                tokenize=True,
                add_generation_prompt=False,
                enable_thinking=False,
            )
            # apply_chat_template adds special tokens for the whole message; recompute a clean segment
            # to avoid duplicated bos/eos artifacts when concatenating roles.
            seg = tokenizer.encode(content, add_special_tokens=False)
            if role == "assistant":
                # Wrap assistant text in chat template tokens so model learns the reply format
                wrapped = tokenizer.apply_chat_template(
                    [{"role": "assistant", "content": content}],
                    tokenize=True,
                    add_generation_prompt=False,
                    enable_thinking=False,
                )
                # Keep only the delta that belongs to assistant content
                seg = wrapped[len(encoded) - len(seg):] if len(encoded) >= len(seg) else wrapped
                token_ids.extend(seg)
                labels.extend(seg)
            else:
                token_ids.extend(encoded)
                labels.extend([-100] * len(encoded))

        out.append({"input_ids": token_ids, "labels": labels})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for Qwen3 on EPANET engineering data")
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B")
    parser.add_argument("--train-file", default="ai_module/data/sft_datasets/train_qwen3_chatml.jsonl")
    parser.add_argument("--val-file", default="ai_module/data/sft_datasets/val_qwen3_chatml.jsonl")
    parser.add_argument("--output-dir", default=str(LORA_ADAPTER_PATH))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--no-4bit", action="store_true", help="Disable 4-bit quantization (CPU / low-VRAM)")
    args = parser.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    print(f"[train_qlora] Loading tokenizer: {args.base_model}")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"[train_qlora] Loading base model: {args.base_model} (4-bit: {not args.no_4bit})")
    bnb_config = None
    if not args.no_4bit:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False

    if not args.no_4bit:
        model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    print(f"[train_qlora] Loading datasets...")
    train_rows = load_jsonl(Path(args.train_file))
    val_rows = load_jsonl(Path(args.val_file))

    train_encoded = build_text_with_masking(train_rows, tokenizer)
    val_encoded = build_text_with_masking(val_rows, tokenizer)

    from datasets import Dataset
    train_ds = Dataset.from_list(train_encoded)
    val_ds = Dataset.from_list(val_encoded)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch",
        save_total_limit=2,
        bf16=torch.cuda.is_available(),
        fp16=False,
        optim="paged_adamw_8bit" if not args.no_4bit else "adamw_torch",
        report_to=[],
        gradient_checkpointing=True,
    )

    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=data_collator,
    )

    trainer.train()
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"[train_qlora] LoRA adapter saved to {out_dir}")


if __name__ == "__main__":
    main()
