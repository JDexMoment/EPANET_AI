"""Импорт разметки от инженеров.

Инженер присылает JSON, экспортированный из HTML-формы (tools/ExpertCasePack_*.html),
кладёт его в data/cases/inbox/. Этот скрипт:
  * разносит label/gold по кейсам сценария;
  * создаёт кейсы режима «ask» из свободных вопросов эксперта;
  * переносит probe-ответы и данные аннотации;
  * кладёт результат в data/cases/filled/ и пишет отчёт об импорте.

Запуск:
    python -m src.dataset.import_expert_json
    python -m src.dataset.import_expert_json --file data/cases/inbox/batch_exp_01_01__all.json
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .. import common, context_builder

FIELDS_TEXT = ("answer", "report_markdown")


def _merge_case(case: dict, payload: dict, sid: str, expert_id: str, exported_at: str) -> bool:
    """Переносит данные одного кейса. Возвращает True, если кейс стал заполненным."""
    changed = False
    label = payload.get("label") or {}

    # метка уровня сценария — во все кейсы сценария
    if label.get("category") or label.get("severity"):
        case["label"] = {
            "has_problem": label.get("has_problem"),
            "category": label.get("category") or case["label"].get("category"),
            "secondary_categories": label.get("secondary_categories", []),
            "severity": label.get("severity") or case["label"].get("severity"),
            "primary_objects": label.get("primary_objects", []),
            "evidence_refs": label.get("evidence_refs", []),
            "confidence": label.get("confidence") or case["label"].get("confidence"),
            "likely_cause": label.get("likely_cause"),
        }
        changed = True

    # золотой ответ конкретного кейса
    g = (payload.get("cases") or {}).get(case["case_id"], {})
    if g:
        gold = case["gold"]
        if g.get("answer"):
            gold["answer"] = g["answer"].strip()
            changed = True
        if g.get("report_markdown"):
            gold["report_markdown"] = g["report_markdown"].strip()
        structured = gold["answer_structured"]
        for key in ("observations", "checks", "recommendations", "limitations"):
            if g.get(key):
                structured[key] = [s for s in g[key] if str(s).strip()]
        if g.get("probable_causes"):
            structured["probable_causes"] = [c for c in g["probable_causes"] if c.get("text")]
        if label.get("evidence_refs"):
            structured["evidence_refs"] = label["evidence_refs"]

    # probe-ответы
    probes = payload.get("probes") or {}
    for pq in case.get("probe_questions", []):
        if probes.get(pq["id"]):
            pq["answer"] = probes[pq["id"]].strip()

    case["annotation"] = {
        "annotator_id": expert_id,
        "annotator_role": "инженер-гидравлик",
        "annotated_at": exported_at,
        "time_spent_min": payload.get("time_spent_min"),
        "double_annotated": bool(payload.get("_double")),
        "reviewer_id": None,
        "review_status": "submitted" if changed else "draft",
        "review_comments": payload.get("review_comments"),
    }
    return changed


def import_file(fp: Path, pending_dir: Path, filled_dir: Path) -> dict:
    data = common.read_json(fp)
    exported_at = data.get("exported_at", common.now_iso())
    expert_id = data.get("expert_id", "unknown")
    stats = {"file": fp.name, "expert": expert_id, "cases": 0, "filled": 0, "new_ask_cases": 0, "scenarios": []}

    for sid, payload in (data.get("scenarios") or {}).items():
        case_files = sorted(pending_dir.glob(f"c_{sid}__*.json"))
        if not case_files:
            stats["scenarios"].append({"scenario_id": sid, "error": "нет кейсов в pending"})
            continue
        for cf in case_files:
            case = common.read_json(cf)
            stats["cases"] += 1
            if _merge_case(case, payload, sid, expert_id, exported_at):
                stats["filled"] += 1
            common.write_json(filled_dir / cf.name, case)

        # свободные вопросы эксперта → новые кейсы режима «ask»
        n_existing = len(list(filled_dir.glob(f"c_{sid}__ask__*.json")))
        for j, fq in enumerate(payload.get("free") or []):
            q = (fq.get("question") or "").strip()
            a = (fq.get("answer") or "").strip()
            if not q:
                continue
            case = common.read_json(case_files[0])
            case["case_id"] = f"c_{sid}__ask__{n_existing + j:02d}"
            case["mode"] = "ask"
            case["question"] = q
            case["selection"] = {"type": "whole_network", "id": None}
            case["gold"]["answer"] = a or None
            # метка сценария наследуется и на ask-кейс
            _merge_case(case, {"label": payload.get("label", {}), "cases": {}}, sid, expert_id, exported_at)
            case["annotation"]["review_status"] = "submitted" if a else "draft"
            # контекст режима «ask»: собираем и замораживаем (как увидит модель)
            try:
                sdir = common.ROOT / "data" / "scenarios" / sid
                ctx = context_builder.build_context(sdir, mode="ask", question=q)
                ctx_name = f"llm_context_ask_{n_existing + j:02d}.json"
                common.write_json(sdir / "derived" / ctx_name, ctx)
                case["facts"]["llm_context_ref"] = str((sdir / "derived" / ctx_name).relative_to(common.ROOT))
                case["facts"]["context_digest"] = common.sha256_text(
                    (sdir / "derived" / ctx_name).read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                case["annotation"]["review_comments"] = f"контекст ask не собран: {e}"
            common.write_json(filled_dir / f"{case['case_id']}.json", case)
            stats["new_ask_cases"] += 1

        stats["scenarios"].append({"scenario_id": sid, "cases": len(case_files)})
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Импорт разметки инженеров")
    ap.add_argument("--inbox", default="data/cases/inbox")
    ap.add_argument("--pending", default="data/cases/pending")
    ap.add_argument("--filled", default="data/cases/filled")
    ap.add_argument("--file", default=None)
    args = ap.parse_args()

    inbox = common.ensure_dir(common.ROOT / args.inbox)
    pending = common.ROOT / args.pending
    filled = common.ensure_dir(common.ROOT / args.filled)

    files = [Path(args.file)] if args.file else sorted(inbox.glob("*.json"))
    if not files:
        print(f"В {inbox} нет файлов разметки.\n"
              f"Инженер экспортирует JSON из HTML-формы и кладёт его в эту папку.")
        return

    total = {"files": 0, "cases": 0, "filled": 0, "ask": 0}
    for fp in files:
        st = import_file(fp, pending, filled)
        total["files"] += 1; total["cases"] += st["cases"]
        total["filled"] += st["filled"]; total["ask"] += st["new_ask_cases"]
        print(f"{st['file']}: сценариев {len(st['scenarios'])}, кейсов {st['cases']}, заполнено {st['filled']}, "
              f"новых ask-кейсов {st['new_ask_cases']}")
        # архивируем принятый файл
        done = common.ensure_dir(inbox / "imported")
        shutil.move(str(fp), str(done / fp.name))

    print(f"\nИтого: файлов {total['files']}, кейсов {total['cases']}, заполнено {total['filled']}, "
          f"ask-кейсов {total['ask']} → {filled}")
    print("Дальше: validate_cases.py → check_quality.py → export_instruct.py")


if __name__ == "__main__":
    main()
