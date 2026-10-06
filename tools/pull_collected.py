"""Забрать данные, собранные сервисом разметки, и превратить их в датасет обучения.

Работает в двух режимах:
  1) скачивает свежий экспорт с сервера (по адресу и админ-токену);
  2) берёт локальный архив (например, уже скачанный из админки).

Дальше по желанию сразу прогоняет штатный конвейер: валидация → качество → сплиты.

Примеры:
    # с сервера
    python tools/pull_collected.py --url https://epanet.example.com --token demo-admin

    # из локального файла, с полным прогоном конвейера
    python tools/pull_collected.py --zip ~/collected_20261006_100951.zip --pipeline
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import common     # noqa: E402

DEST = common.ROOT / "data" / "collected"


def download(url: str, token: str, out: Path) -> Path:
    url = url.rstrip("/") + "/api/admin/export?name=latest.zip&token=" + urllib.parse.quote(token)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Скачиваю {url.split('?')[0]} …")
    req = urllib.request.Request(url, headers={"X-Admin-Token": token})
    with urllib.request.urlopen(req, timeout=600) as r, out.open("wb") as f:
        shutil.copyfileobj(r, f)
    return out


def unpack(zip_path: Path) -> dict:
    # данные в data/collected пересобираются с нуля; если сам архив лежит внутри
    # этого каталога, уносим его во временное место, иначе он будет удалён вместе с ним
    zip_path = Path(zip_path)
    if DEST.resolve() in zip_path.resolve().parents:
        tmp = Path(tempfile.gettempdir()) / zip_path.name
        shutil.copyfile(zip_path, tmp)
        zip_path = tmp
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(DEST)
    cases = sorted((DEST / "cases").glob("c_*.json"))
    # ссылки на контекст в архиве относительны (contexts/<model>/...); в проекте
    # кейсы лежат в data/collected/, поэтому дописываем префикс — иначе обучение
    # получило бы пустой контекст
    prefix = str(DEST.relative_to(common.ROOT))
    fixed = 0
    for cf in cases:
        case = json.loads(cf.read_text(encoding="utf-8"))
        ref = ((case.get("facts") or {}).get("llm_context_ref") or "")
        if ref and not ref.startswith(prefix) and not (common.ROOT / ref).exists():
            case.setdefault("facts", {})["llm_context_ref"] = f"{prefix}/{ref}"
            cf.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
            fixed += 1
    if fixed:
        print(f"  ссылки на контекст приведены к путям проекта: {fixed}")
    # возвращаем маркеры каталогов, чтобы структура data/ осталась полной
    for sub in ("cases", "models", "contexts"):
        d = DEST / sub
        if d.exists():
            (d / ".gitkeep").touch()
    manifest = {}
    mp = DEST / "manifest.json"
    if mp.exists():
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    print(f"Распаковано в {DEST.relative_to(common.ROOT)}: кейсов {len(cases)}, "
          f"моделей {len(list((DEST / 'models').glob('*'))) if (DEST / 'models').exists() else 0}")
    return {"manifest": manifest, "cases": len(cases)}


def run_pipeline() -> None:
    steps = [
        [sys.executable, "-m", "src.dataset.validate_cases", "--dir", "data/collected/cases",
         "--report", "data/eval/validation_report_collected.json"],
        [sys.executable, "-m", "src.dataset.check_quality", "--dir", "data/collected/cases",
         "--out", "data/eval/quality_report_collected.json"],
        [sys.executable, "-m", "src.dataset.export_instruct", "--dir", "data/collected/cases",
         "--include-candidates", "--out", "data/splits_collected"],
        [sys.executable, "-m", "src.eval.metrics_offline", "--splits", "data/splits_collected"],
    ]
    for cmd in steps:
        print("\n$ " + " ".join(cmd[1:]))
        r = subprocess.run(cmd, cwd=common.ROOT)
        if r.returncode != 0:
            print("  шаг завершился с ошибкой — останавливаюсь")
            return
    print("\nГотово. Датасет собранных данных: data/splits_collected/ (train/val/test + eval_test)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Забрать данные сервиса разметки в датасет")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="адрес сервиса, например https://epanet.example.com")
    g.add_argument("--zip", help="локальный архив экспорта")
    ap.add_argument("--token", default=None, help="ADMIN_TOKEN сервиса (для --url)")
    ap.add_argument("--out", default=str(DEST / "download.zip"))
    ap.add_argument("--pipeline", action="store_true", help="сразу прогнать валидацию и сплиты")
    ap.add_argument("--keep-zip", action="store_true")
    args = ap.parse_args()

    if args.url:
        token = args.token or input("ADMIN_TOKEN: ").strip()
        zip_path = download(args.url, token, Path(args.out))
    else:
        zip_path = Path(args.zip).expanduser()
        if not zip_path.exists():
            print(f"Нет файла {zip_path}")
            return

    info = unpack(zip_path)
    if info["manifest"]:
        m = info["manifest"]
        print(f"Экспорт от {m.get('exported_at')}: кейсов {m.get('annotations')}, "
              f"эксперты {m.get('experts')}, типы {m.get('kinds')}")
    if args.pipeline:
        run_pipeline()
    else:
        print("Дальше:  python -m src.dataset.validate_cases --dir data/collected/cases")
    if not args.keep_zip and args.url:
        zip_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
