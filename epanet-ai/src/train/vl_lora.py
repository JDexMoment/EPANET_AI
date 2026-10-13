"""План и подготовка обучения VLM на скриншотах (Qwen3-VL + LoRA).

Что делает этот скрипт:
  1) проверяет датасет (файлы сплитов, наличие картинок, длину ответов);
  2) считает бюджет: сколько шагов, сколько памяти нужно, куда сохранять адаптер;
  3) печатает (и при желании записывает) готовую команду обучения для
     ms-swift либо готовый скрипт на transformers+peft (TRL).

Сам процесс обучения запускается на машине с GPU — здесь только подготовка,
потому что это единственное место, где нужны torch, transformers и видеокарта.

Запуск:
    python -m src.train.vl_lora                     # план по датасету
    python -m src.train.vl_lora --emit-script outputs/train_vl.sh
    python -m src.train.vl_lora --backend transformers --emit-script outputs/train_vl.py
"""
from __future__ import annotations

import argparse
import shutil
from string import Template
from pathlib import Path

from .. import common
from ..vision import preprocess as pp


def check_dataset(data_dir: Path, cfg: dict) -> tuple[dict, list[str]]:
    problems: list[str] = []
    stats = {"train": 0, "val": 0, "test": 0, "images_missing": 0,
             "image_pixels": [], "answer_words": [], "groups": 0}
    groups: set[str] = set()

    for split in ("train", "val", "test"):
        f = data_dir / f"{split}.jsonl"
        if not f.exists():
            problems.append(f"нет файла {common.rel_to_root(f)} — сначала build_vl_dataset")
            continue
        rows = common.read_jsonl(f)
        stats[split] = len(rows)
        for r in rows:
            groups.add(r.get("group", "?"))
            img = Path(r["image"])
            if not img.is_absolute():
                img = common.ROOT / img
            if not img.exists():
                stats["images_missing"] += 1
                continue
            stats["image_pixels"].append(r["meta"].get("width", 0) * r["meta"].get("height", 0) or
                                         img.stat().st_size)
            stats["answer_words"].append(len(r["answer"].split()))
    stats["groups"] = len(groups)
    return stats, problems


def budget(stats: dict, cfg: dict) -> dict:
    t = cfg["training"]
    steps_per_epoch = max(1, stats["train"] // max(1, t["gradient_accumulation_steps"]))
    est_seq_tokens = cfg["training"]["image_max_token_num"] + 700      # изображение + вопрос и ответ
    base = cfg["model"]["primary"].lower()
    lora_vram = 8.0 if "4b" in base else (14.0 if "8b" in base else (5.0 if "2b" in base else 10.0))
    return {"steps_total": steps_per_epoch * t["num_train_epochs"] * max(1, stats["groups"] // 8 + 1),
            "steps_per_epoch": steps_per_epoch,
            "est_seq_tokens": est_seq_tokens,
            "vram_lora_gb": round(lora_vram, 1),
            "vram_qlora_gb": round(lora_vram * 0.55, 1),
            "approx_minutes": int(steps_per_epoch * t["num_train_epochs"] * 6)}


def swift_command(cfg: dict, stats: dict) -> str:
    t, d = cfg["training"], cfg["deployment"]
    model = cfg["model"]["primary"]
    env = (f"IMAGE_MAX_TOKEN_NUM={t['image_max_token_num']} "
           f"PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True")
    return " \\\n    ".join([
        env,
        "swift sft",
        f"--model {model}",
        f'--dataset "{common.ROOT / "data/screens/swift_train.jsonl"}"',
        f'--val_dataset "{common.ROOT / "data/screens/swift_val.jsonl"}"',
        f"--tuner_type lora --lora_rank {t['lora_rank']} --lora_alpha {t['lora_alpha']} "
        f"--lora_dropout {t['lora_dropout']}",
        f"--target_modules {t['target_modules']} --freeze_vit {str(t['freeze_vit']).lower()} "
        f"--freeze_aligner {str(t['freeze_aligner']).lower()}",
        f"--torch_dtype bfloat16",
        f"--num_train_epochs {t['num_train_epochs']}",
        f"--per_device_train_batch_size {t['per_device_train_batch_size']} "
        f"--gradient_accumulation_steps {t['gradient_accumulation_steps']}",
        f"--learning_rate {t['learning_rate']} --lr_scheduler_type cosine --warmup_ratio {t['warmup_ratio']}",
        f"--max_length {t['max_length']} --gradient_checkpointing {str(t['gradient_checkpointing']).lower()}",
        f"--save_steps {t['save_steps']} --logging_steps {t['logging_steps']} --save_total_limit 3",
        f"--output_dir \"{common.ROOT / t['output_dir']}\"",
    ])


TRANSFORMERS_TEMPLATE = Template('''"""Обучение Qwen3-VL на скриншотах: LoRA через transformers + peft (TRL-free, минимум зависимостей).

Сгенерировано src/train/vl_lora.py. Требует: torch, transformers>=4.57, peft, pillow.
Запуск (на машине с GPU):
    python outputs/train_vl_transformers.py --data data/screens --out outputs/qwen3vl-epanet-screens-v1
"""
import argparse, json
from pathlib import Path

import torch
from PIL import Image
from peft import LoraConfig, get_peft_model
from torch.utils.data import Dataset
from transformers import AutoModelForImageTextToText, AutoProcessor, Trainer, TrainingArguments


class ScreensDataset(Dataset):
    """Датасет «скриншот + вопрос → золотой ответ». Формат строк — swift_*.jsonl."""

    def __init__(self, rows, processor):
        self.rows = rows
        self.processor = processor

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        row = self.rows[i]
        image = Image.open(row["images"][0]).convert("RGB")
        messages = row["messages"]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        enc = self.processor(text=[text], images=[image], return_tensors="pt", padding=True)
        item = {k: v[0] for k, v in enc.items()}
        labels = item["input_ids"].clone()
        # обучаем только на ответе: маскируем всё до последней реплики assistant
        labels[:] = torch.where(labels == self.processor.tokenizer.pad_token_id, -100, labels)
        item["labels"] = labels
        return item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/screens")
    ap.add_argument("--model", default="$model")
    ap.add_argument("--out", default="$out_dir")
    ap.add_argument("--epochs", type=float, default=$epochs)
    ap.add_argument("--lr", type=float, default=$lr)
    ap.add_argument("--rank", type=int, default=$rank)
    ap.add_argument("--batch", type=int, default=$batch)
    ap.add_argument("--accum", type=int, default=$accum)
    ap.add_argument("--max-length", type=int, default=$max_length)
    ap.add_argument("--smoke", action="store_true", help="10 шагов, чтобы проверить, что всё работает")
    args = ap.parse_args()

    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForImageTextToText.from_pretrained(args.model, torch_dtype=torch.bfloat16,
                                                        device_map="auto")
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM", target_modules="all-linear"))

    def load(split):
        p = Path(args.data) / f"swift_{{split}}.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    train_rows, val_rows = load("train"), load("val")
    tr = TrainingArguments(
        output_dir=args.out, num_train_epochs=args.epochs, learning_rate=args.lr,
        per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.accum,
        gradient_checkpointing=True, bf16=True, logging_steps=5, save_steps=50,
        save_total_limit=3, warmup_ratio=0.03, lr_scheduler_type="cosine",
        eval_strategy="steps" if val_rows else "no", eval_steps=50, report_to="none",
        max_steps=10 if args.smoke else -1)
    trainer = Trainer(model=model, args=tr,
                      train_dataset=ScreensDataset(train_rows, processor),
                      eval_dataset=ScreensDataset(val_rows, processor) if val_rows else None)
    trainer.train()
    trainer.save_model(args.out)
    processor.save_pretrained(args.out)
    print("Адаптер сохранён:", args.out)
    print("Дальше: merge LoRA → convert_hf_to_gguf → llama-quantize (см. docs/09, раздел 8)")


if __name__ == "__main__":
    main()
''')


def main() -> None:
    ap = argparse.ArgumentParser(description="План обучения VLM на скриншотах")
    ap.add_argument("--data", default="data/screens", help="каталог датасета (после build_vl_dataset)")
    ap.add_argument("--emit-script", default=None, help="записать готовую команду/скрипт в файл")
    ap.add_argument("--backend", choices=["swift", "transformers"], default=None,
                    help="по умолчанию берётся из configs/vision.yaml")
    ap.add_argument("--print-plan", action="store_true", help="печатать план (по умолчанию и так печатает)")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/vision.yaml")
    backend = args.backend or cfg["training"]["backend"]
    data_dir = common.ROOT / args.data

    print("=" * 78)
    print("ПЛАН ОБУЧЕНИЯ ЛОКАЛЬНОЙ МОДЕЛИ (скриншоты → ответ)")
    print("=" * 78)
    print(f"  базовая модель:   {cfg['model']['primary']}")
    print(f"  если есть GPU 8 ГБ: {cfg['model']['if_gpu_8gb']}")
    print(f"  очень слабый ПК:  {cfg['model']['if_very_weak']}")
    print(f"  метод:            LoRA r={cfg['training']['lora_rank']}, "
          f"ViT заморожен: {cfg['training']['freeze_vit']}")
    print(f"  бэкенд:           {backend}")

    if not data_dir.exists():
        print("\n  Датасета ещё нет: положите присланные данные в data/screens/raw и выполните")
        print("     python -m src.dataset.import_screenshots --src data/screens/raw")
        print("     python -m src.dataset.check_screenshot_pairs")
        print("     python -m src.dataset.build_vl_dataset --copy-images")
        return

    stats, problems = check_dataset(data_dir, cfg)
    print(f"\n  датасет: train {stats['train']} · val {stats['val']} · test {stats['test']} "
          f"· групп {stats['groups']}")
    if stats["answer_words"]:
        avg = sum(stats["answer_words"]) / len(stats["answer_words"])
        print(f"  ответы: в среднем {avg:.0f} слов (мин {min(stats['answer_words'])}, "
              f"макс {max(stats['answer_words'])})")
    for p in problems:
        print(f"  ✗ {p}")
    if stats["images_missing"]:
        print(f"  ✗ не найдено файлов изображений: {stats['images_missing']}")

    if not problems and stats["train"]:
        b = budget(stats, cfg)
        print(f"\n  шагов оптимизации за эпоху: ~{b['steps_per_epoch']}, всего ~{b['steps_total']}")
        print(f"  длина последовательности:   ~{b['est_seq_tokens']} токенов")
        print(f"  видеопамять:                LoRA (bf16) ~{b['vram_lora_gb']} ГБ · "
              f"QLoRA (4-бит) ~{b['vram_qlora_gb']} ГБ")
        print("  подсказка:                  на GPU 8 ГБ берите QLoRA или 4B/2B модель; "
              "на 16 ГБ+ — 8B в bf16")
        print(f"  ориентир времени:           ~{b['approx_minutes']} мин на 1 GPU")
        print(f"  адаптер:                    {cfg['training']['output_dir']}")
        if stats["train"] < 60:
            print("  ! обучающих примеров мало: LoRA покажет эффект от ~200-300 пар,")
            print("    меньше — можно проверить механику, но не качество.")

    print("\n  Важно про железо клиента: обучение — на вашей машине с GPU (аренда на часы),")
    print("  а у клиента модель только отвечает: {:.1f} ГБ в {} + mmproj {}.".format(
        2.5 if "4b" in cfg["model"]["primary"].lower() else 3.7,
        cfg["deployment"]["quant_primary"], cfg["deployment"]["mmproj"]))

    if data_dir.exists() and not problems:
        if backend == "swift":
            script = ("#!/usr/bin/env bash\n"
                      "# Обучение Qwen3-VL на скриншотах (ms-swift). Запуск: bash этот_файл\n"
                      "set -euo pipefail\n\n"
                      + swift_command(cfg, stats) + "\n")
        else:
            t = cfg["training"]
            script = TRANSFORMERS_TEMPLATE.substitute(
                model=cfg["model"]["primary"], out_dir=t["output_dir"], epochs=t["num_train_epochs"],
                lr=t["learning_rate"], rank=t["lora_rank"],
                batch=t["per_device_train_batch_size"], accum=t["gradient_accumulation_steps"],
                max_length=t["max_length"])

        if args.emit_script:
            out = common.ROOT / args.emit_script
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(script, encoding="utf-8")
            try:
                shown = common.rel_to_root(out)
            except ValueError:
                shown = out
            print(f"\n  Готовый скрипт обучения: {shown}")
        else:
            print("\n  Команда обучения (записать в файл: --emit-script outputs/train_vl.sh):")
            for line in script.splitlines():
                print("    " + line)


if __name__ == "__main__":
    main()
