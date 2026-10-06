"""QLoRA-SFT для инженерного ассистента EPANET.

Базовая модель по решению проекта (configs/model.yaml): **Qwen/Qwen3.5-9B**.
Запасные варианты: Qwen3.5-4B (слабые ПК), Qwen3.5-35B-A3B (мощные машины).

ВАЖНО: скрипт запускается на машине с GPU (torch/transformers/peft/trl).
В песочнице подготовки данных он не обучает, но полностью проверяет план:
    python -m src.train.qlora_sft --print-plan

Запуск обучения:
    pip install torch transformers peft trl bitsandbytes datasets accelerate
    python -m src.train.qlora_sft \
        --train data/splits/train.jsonl --val data/splits/val.jsonl \
        --out outputs/qwen3.5-9b-epanet-v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import common     # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def load_model_cfg() -> dict:
    p = common.ROOT / "configs" / "model.yaml"
    return common.load_yaml(str(p)) if p.exists() else {}


def parse_args() -> argparse.Namespace:
    cfg = load_model_cfg().get("training", {}) or {}

    ap = argparse.ArgumentParser(description="QLoRA-SFT для EPANET-AI (по умолчанию Qwen3.5-9B)")
    ap.add_argument("--model", default=cfg.get("model", "Qwen/Qwen3.5-9B"))
    ap.add_argument("--train", default="data/splits/train.jsonl")
    ap.add_argument("--val", default="data/splits/val.jsonl")
    ap.add_argument("--out", default="outputs/qwen3.5-9b-epanet-v1")
    ap.add_argument("--lora_r", type=int, default=cfg.get("lora_r", 16))
    ap.add_argument("--lora_alpha", type=int, default=cfg.get("lora_alpha", 32))
    ap.add_argument("--lora_dropout", type=float, default=cfg.get("lora_dropout", 0.05))
    ap.add_argument("--epochs", type=float, default=cfg.get("epochs", 2.0))
    ap.add_argument("--lr", type=float, default=cfg.get("lr", 1.5e-4))
    ap.add_argument("--max_len", type=int, default=cfg.get("max_len", 6144))
    ap.add_argument("--batch", type=int, default=cfg.get("batch", 1))
    ap.add_argument("--grad_accum", type=int, default=cfg.get("grad_accum", 12))
    ap.add_argument("--warmup_ratio", type=float, default=cfg.get("warmup_ratio", 0.04))
    ap.add_argument("--seed", type=int, default=cfg.get("seed", 42))
    ap.add_argument("--bf16", action="store_true", default=cfg.get("bf16", True))
    ap.add_argument("--max_steps", type=int, default=-1, help="для быстрой проверки конвейера")
    ap.add_argument("--print-plan", action="store_true", help="показать план обучения и выйти")
    return ap.parse_args()


def plan(args: argparse.Namespace) -> dict:
    return {
        "model": args.model,
        "dataset": {"train": args.train, "val": args.val},
        "out": args.out,
        "qlora": {"r": args.lora_r, "alpha": args.lora_alpha, "dropout": args.lora_dropout,
                  "targets": ["q_proj", "k_proj", "v_proj", "o_proj",
                              "gate_proj", "up_proj", "down_proj"]},
        "optim": {"lr": args.lr, "epochs": args.epochs, "batch": args.batch,
                  "grad_accum": args.grad_accum, "warmup_ratio": args.warmup_ratio,
                  "scheduler": "cosine", "precision": "bf16", "quant": "nf4 4-bit"},
        "context": {"max_len": args.max_len, "completion_only_loss": True,
                    "enable_thinking": False},
    }


def load_rows(path: Path) -> list[dict]:
    rows = common.read_jsonl(path)
    for r in rows:
        if "messages" not in r or len(r["messages"]) < 3:
            raise ValueError(f"ожидается chat-формат с 3 сообщениями, получено: {list(r)[:4]}")
    return rows


def main() -> None:
    args = parse_args()
    model_cfg = load_model_cfg()
    p = plan(args)
    print("План обучения (QLoRA-SFT):")
    print(json.dumps(p, ensure_ascii=False, indent=2))
    decision = (model_cfg.get("decision") or {})
    if decision:
        print(f"Решение по модели: {decision.get('date')} — {decision.get('base_model')} "
              f"({decision.get('status')})")
    if args.print_plan:
        return

    train_path = common.ROOT / args.train
    val_path = common.ROOT / args.val
    out_dir = common.ROOT / args.out
    if not train_path.exists():
        print(f"\nНет файла {train_path} — сначала разметьте кейсы и запустите "
              f"python -m src.dataset.export_instruct")
        return

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as e:  # pragma: no cover
        print("\nНе установлены зависимости обучения:", e)
        print("pip install torch transformers peft trl bitsandbytes datasets accelerate")
        return

    rows = load_rows(train_path)
    val_rows = load_rows(val_path) if val_path.exists() else []
    print(f"\ntrain: {len(rows)} примеров, val: {len(val_rows)}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if getattr(tokenizer, "chat_template", None) is None:
        print("[warn] у модели нет chat_template — проверьте, что это instruct-чекпойнт")

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map="auto",
        torch_dtype=torch.bfloat16, trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def to_text(row: dict) -> dict:
        return {"text": tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=False,
            enable_thinking=False)}

    train_ds = Dataset.from_list([to_text(r) for r in rows])
    val_ds = Dataset.from_list([to_text(r) for r in val_rows]) if val_rows else None

    cfg = SFTConfig(
        output_dir=str(out_dir), num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=args.warmup_ratio,
        bf16=args.bf16, max_length=args.max_len, max_steps=args.max_steps,
        logging_steps=10, save_strategy="epoch", eval_strategy="epoch" if val_ds else "no",
        seed=args.seed, gradient_checkpointing=True, report_to=[],
        completion_only_loss=True,      # учим только ответ ассистента, контекст не «учим»
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=train_ds,
                         eval_dataset=val_ds, processing_class=tokenizer)
    trainer.train()
    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    run_meta = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_model": args.model,
        "model_decision": {"date": decision.get("date"), "status": decision.get("status")},
        "dataset": {"train": args.train, "train_sha256_16": sha256(train_path),
                    "train_examples": len(rows),
                    "val_sha256_16": sha256(val_path)[:16] if val_path.exists() else None},
        "hyperparams": p["qlora"] | p["optim"] | {"max_len": args.max_len, "seed": args.seed},
        "next_step": "python -m src.eval.metrics_model --pred data/eval/predictions.jsonl "
                     "--eval-set data/splits/eval_test.jsonl",
        "quantize_for_client": (model_cfg.get("quantization") or {}).get("note", ""),
    }
    common.ensure_dir(out_dir)
    (out_dir / "run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(f"Готово → {out_dir} (адаптер + run.json)")


if __name__ == "__main__":
    main()
