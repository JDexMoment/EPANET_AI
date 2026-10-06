"""Выгрузка собранных данных в датасет обучения + автономный автоэкспорт.

Задача: сервис работает сам (на сервере), а владелец проекта в любой момент забирает
готовый архив и превращает его в датасет обучения штатным конвейером:
    tools/pull_collected.py → data/collected/ → import/validate → data/splits
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, modeling, storage

ROOT = config.ROOT


# ─────────────────────────── аннотация → кейс датасета

def _ctx_ref(model_id: str, mode: str) -> str:
    """Ссылка на контекст ВНУТРИ архива сбора данных.

    Форма одна и та же независимо от того, где лежат данные сервиса
    (service_data рядом с кодом или /data в Docker): contexts/<model>/llm_context_<mode>.json.
    Контексты кладутся в архив при экспорте (см. build_export), а pull_collected.py
    переписывает ссылку в путь проекта (data/collected/<...>).
    """
    return f"contexts/{model_id}/llm_context_{mode}.json"

def annotation_to_case(ann: dict, model: dict) -> dict:
    """Собирает кейс в формате schemas/case.schema.json (то, что понимает датасет-конвейер)."""
    model_id = ann["model_id"]
    evidence: list[dict] = []
    ctx_text = ""
    ctx_ref = None
    mode = ann["mode"]
    sdir = modeling.model_dir(model_id)
    used_mode = None
    for cand_mode in (mode, "whats_happening"):
        cand = sdir / "derived" / f"llm_context_{cand_mode}.json"
        if cand.exists():
            ctx_text = cand.read_text(encoding="utf-8")
            used_mode = cand_mode
            ctx_ref = _ctx_ref(model_id, cand_mode)
            break
    ev_path = sdir / "derived" / "evidence.json"
    if ev_path.exists():
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        refs = [r for r in (ann.get("evidence_refs") or "").split(",") if r]
        if refs:
            evidence = [ev[k] for k in refs if k in ev]
        else:
            evidence = list(ev.values())[:40]

    objects = (ann.get("object_id") or "").split(",") if ann.get("object_id") else []
    objects = [o.strip() for o in objects if o.strip()]
    selection = _selection(objects, model)
    structured = {
        "observations": _lines(ann.get("observations")),
        "probable_causes": [{"text": t} for t in _lines(ann.get("causes"))],
        "checks": _lines(ann.get("checks")),
        "recommendations": _lines(ann.get("recommendations")),
        "limitations": _lines(ann.get("limitations")),
        "evidence_refs": [r for r in (ann.get("evidence_refs") or "").split(",") if r],
    }
    structured = {k: v for k, v in structured.items() if v}

    short = hashlib.sha1(ann["id"].encode()).hexdigest()[:6]
    case_id = f"c_up_{model_id}__{mode}__{short}"
    case = {
        "schema_version": "1.0",
        "case_id": case_id,
        "scenario_id": f"up_{model_id}",
        "mode": mode,
        "question": ann.get("question") or _default_question(mode),
        "selection": selection,
        "facts": {
            "context_digest": hashlib.sha256(ctx_text.encode()).hexdigest()[:16] if ctx_text else None,
            "llm_context_ref": ctx_ref,
            "evidence": evidence,
            "source": "collection_service",
            "uploaded_filename": model.get("filename"),
            "clean_inp": model.get("clean_inp"),
        },
        "label": {
            "has_problem": (ann.get("severity") or "info") not in ("no_problem", "none"),
            "category": ann.get("category") or "unknown",
            "severity": ann.get("severity") or "info",
            "primary_objects": objects,
            "evidence_refs": structured.get("evidence_refs", []),
            "confidence": ann.get("confidence") or "medium",
            "likely_cause": (structured.get("probable_causes") or [{}])[0].get("text"),
        },
        "gold": {
            "answer": ann.get("answer") or "",
            "answer_structured": structured or None,
            "report_markdown": ann.get("report_markdown") or None,
        },
        "probe_questions": [],
        "annotation": {
            "annotator_id": ann.get("expert_id"),
            "annotated_at": ann.get("created_at"),
            "time_spent_min": ann.get("time_spent_min"),
            # статус из схемы датасета: submitted = сдано инженером, ждёт ревью ведущего.
            # Факт сбора сервисом виден отдельным полем source.
            "review_status": "submitted",
            "source": "collection_service",
            "model_id": model_id,
            "number_check": json.loads(ann["number_check_json"]) if ann.get("number_check_json") else None,
        },
        "eval": {},
    }
    return {k: v for k, v in case.items() if v is not None}


ALLOWED_SELECTION_TYPES = {"junction", "pipe", "pump", "tank", "reservoir", "valve",
                           "zone", "whole_network"}


def _selection(objects: list[str], model: dict) -> dict:
    """Тип объекта для selection берём из таблицы объектов модели (схема датасета строгая)."""
    if not objects:
        return {"type": "whole_network", "id": None}
    try:
        table = json.loads(model.get("objects_json") or "[]")
    except Exception:  # noqa: BLE001
        table = []
    kinds = {o.get("id"): o.get("type") for o in table}
    oid = objects[0]
    otype = kinds.get(oid)
    if otype in ALLOWED_SELECTION_TYPES:
        return {"type": otype, "id": oid}
    return {"type": "whole_network", "id": None}


def _lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [l.strip(" -•\t") for l in text.splitlines() if l.strip(" -•\t")]


def _default_question(mode: str) -> str:
    return {
        "whats_happening": "Что происходит в сети?",
        "explain_object": "Объясните состояние выбранного объекта.",
        "find_problems": "Какие проблемы видны в расчёте?",
        "why_happened": "Почему возникла эта ситуация?",
        "make_report": "Составьте инженерный отчёт по расчёту.",
        "compare_scenarios": "Что изменилось по сравнению с предыдущим расчётом?",
        "ask": "Вопрос инженера.",
    }.get(mode, "Инженерный вопрос.")


# ─────────────────────────── сборка архива
def build_export(only_unexported: bool = True, tag: str | None = None) -> dict:
    anns = storage.list_annotations(only_unexported=only_unexported)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"collected_{tag or ts}.zip"
    path = config.EXPORTS / name
    cases_dir = config.EXPORTS / "_staging" / (tag or ts)
    if cases_dir.exists():
        shutil.rmtree(cases_dir)
    cases_dir.mkdir(parents=True, exist_ok=True)

    used_ids: list[str] = []
    written = 0
    for ann in anns:
        model = storage.get_model(ann["model_id"])
        if not model:
            continue
        case = annotation_to_case(ann, model)
        (cases_dir / f"{case['case_id']}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        used_ids.append(ann["id"])
        written += 1

    models = storage.list_models(limit=1000)
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "annotations": written,
        "models": len(models),
        "experts": sorted({a["expert_id"] for a in anns}),
        "kinds": {k: len([a for a in anns if a["kind"] == k]) for k in ("element_problem", "report", "qa")},
        "how_to_use": [
            "Распакуйте архив в data/collected/ (или запустите tools/pull_collected.py)",
            "python -m src.dataset.validate_cases --dir data/collected/cases",
            "python -m src.dataset.check_quality  --dir data/collected/cases",
            "python -m src.dataset.export_instruct --dir data/collected/cases --include-candidates",
        ],
    }

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for case_file in sorted(cases_dir.glob("*.json")):
            z.write(case_file, f"cases/{case_file.name}")
        z.writestr("annotations_raw.jsonl",
                   "\n".join(json.dumps(a, ensure_ascii=False) for a in anns))
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for m in models:
            mid = m["id"]
            if m.get("clean_inp") and Path(m["clean_inp"]).exists():
                z.write(m["clean_inp"], f"models/{mid}/network_clean.inp")
            orig_dir = config.UPLOADS / mid
            if orig_dir.exists():
                for f in orig_dir.iterdir():
                    if f.is_file():
                        z.write(f, f"models/{mid}/original{f.suffix}")
            mdir = modeling.model_dir(mid)          # service_data/models/up_<id>
            scen = mdir / "scenario.json"
            if scen.exists():
                z.write(scen, f"models/{mid}/scenario.json")
            der = mdir / "derived" / "derived_metrics.json"
            if der.exists():
                z.write(der, f"models/{mid}/derived_metrics.json")
            # контексты для LLM: без них кейс в датасете остаётся без входных данных
            for ctx in sorted((mdir / "derived").glob("llm_context_*.json")):
                z.write(ctx, f"contexts/{mid}/{ctx.name}")
        z.writestr("README.txt", _readme_text(manifest))

    size = path.stat().st_size
    if only_unexported and used_ids:
        storage.mark_exported(used_ids, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    storage.log_event("export", actor="system", file=name, cases=written, bytes=size)

    latest = config.EXPORTS / "latest.zip"
    try:
        shutil.copyfile(path, latest)
    except OSError:
        pass

    if config.BACKUP_CMD:
        try:
            subprocess.run(config.BACKUP_CMD.format(file=str(path)), shell=True, timeout=600, check=False)
            storage.log_event("backup", actor="system", file=name)
        except Exception as e:  # noqa: BLE001
            storage.log_event("backup_failed", actor="system", error=str(e))

    _announce(manifest, path)
    _prune()
    return {"file": name, "path": str(path), "cases": written, "bytes": size, "manifest": manifest}


def _announce(manifest: dict, path: Path) -> None:
    if not config.ANNOUNCE_WEBHOOK:
        return
    try:
        import urllib.request
        body = json.dumps({"text": f"EPANET-AI: собран экспорт {path.name}, "
                                   f"новых кейсов {manifest['annotations']}"}).encode()
        req = urllib.request.Request(config.ANNOUNCE_WEBHOOK, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _readme_text(manifest: dict) -> str:
    return (
        "EPANET-AI — архив собранных данных от инженеров\n"
        "===============================================\n\n"
        f"Собрано: {manifest['exported_at']}\n"
        f"Кейсов: {manifest['annotations']} · моделей: {manifest['models']}\n"
        f"Состав: {manifest['kinds']}\n\n"
        "Что внутри:\n"
        "  cases/*.json        — размеченные кейсы в формате датасета (schemas/case.schema.json)\n"
        "  models/<id>/        — исходная и очищенная модель, сводная аналитика\n"
        "  annotations_raw.jsonl — сырые записи из базы сервиса (для аудита)\n"
        "  manifest.json       — сводка\n\n"
        "Как использовать:\n  " + "\n  ".join(manifest["how_to_use"]) + "\n")


def _prune() -> None:
    files = sorted([p for p in config.EXPORTS.glob("collected_*.zip")],
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[config.KEEP_EXPORTS:]:
        try:
            old.unlink()
        except OSError:
            pass
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    staging = config.EXPORTS / "_staging"
    if staging.exists():
        for d in staging.iterdir():
            try:
                if datetime.fromtimestamp(d.stat().st_mtime, timezone.utc) < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass


def list_exports() -> list[dict]:
    out = []
    for p in sorted(config.EXPORTS.glob("collected_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({"file": p.name, "bytes": st.st_size,
                    "created": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return out
