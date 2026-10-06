"""Связка «экран → контекст → LLM».

Берёт результат detect_screen (JSON), решает, в каком режиме отвечать, и собирает
тот же llm_context, что и текстовый путь: модель получает контекст расчёта + блок
`request.ui` с описанием экрана. Если объект/шаг времени определён ненадёжно —
возвращается уточняющий вопрос (assistant НЕ отвечает наугад).

Запуск:
    python -m src.vision.screen_to_context \
        --screen data/screen_labels/pred/map_j105.json \
        --scenario data/scenarios/vn01__demand_increase__J105__225 \
        --question "Почему упало давление?" --out /tmp/ctx_ui.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import analytics, common, context_builder     # noqa: E402
from src.vision import detect_screen as ds             # noqa: E402


MODE_BY_SCREEN = {
    "map": "whats_happening",
    "results_table": "whats_happening",
    "object_editor": "explain_object",
    "time_series": "whats_happening",
    "report": "make_report",
    "form": "ask",
    "dialog": "ask",
    "unknown": "ask",
}

MODE_BY_QUESTION = [
    (("почему", "причин", "из-за", "why"), "why_happened"),
    (("что происход", "что случил", "что не так", "обстановк"), "whats_happening"),
    (("найди", "проблем", "что не в порядке"), "find_problems"),
    (("отчёт", "отчет", "заключени", "report"), "make_report"),
    (("сравн", "отличи", "динамик"), "compare_scenarios"),
    (("объясни", "расскажи про", "поясни"), "explain_object"),
]


def mode_for(screen: dict, question: str | None) -> str:
    q = (question or "").lower()
    for keys, mode in MODE_BY_QUESTION:
        if any(k in q for k in keys):
            # compare_scenarios для одиночного экрана бессмысленен без базового контекста
            if mode == "compare_scenarios" and screen["screen_type"] != "time_series":
                continue
            return mode
    sel = screen.get("selected_object")
    if sel and screen["screen_type"] in ("map", "object_editor", "time_series"):
        return "explain_object"
    return MODE_BY_SCREEN.get(screen["screen_type"], "ask")


def build_ui_block(screen: dict, question: str | None = None) -> dict:
    ui = dict(screen.get("ui_context") or {})
    ui["source"] = "screen_understanding"
    ui["user_question"] = question
    ui["actions"] = [a["intent"] for a in screen.get("actions", [])]
    ui["ambiguity"] = screen.get("ambiguity", {}).get("level")
    return ui


def clarify(screen: dict, why: str) -> dict:
    sel = screen.get("selected_object")
    cands = [c["id"] for c in screen.get("ambiguity", {}).get("candidates", [])][:5]
    vo = [v["id"] for v in screen.get("visible_objects", [])][:5]
    return {
        "action": "ask_user",
        "reason": why,
        "question": ("Уточните, пожалуйста, объект, который вас интересует"
                     + (f": {', '.join(cands)}?" if cands else " (на экране их несколько).")),
        "detected": {"screen_type": screen.get("screen_type"),
                     "selected_object": (sel or {}).get("id"),
                     "timestep_h": (screen.get("timestep") or {}).get("hour"),
                     "confidence": screen.get("confidence")},
        "candidates": cands,
        "visible_objects": vo,
    }


def compose(screen_path: str | Path, scenario_dir: str | Path, question: str | None = None,
            out: str | Path | None = None) -> dict:
    cfg = common.load_yaml("configs/ui.yaml")
    screen = json.loads(Path(screen_path).read_text(encoding="utf-8"))
    scenario_dir = Path(scenario_dir)

    # 1) низкая уверенность — сначала уточняем
    threshold = cfg["ambiguity"]["ask_user_below_confidence"]
    deictic = any(w in (question or "").lower() for w in
                  ("этот", "этом", "это ", "здесь", "тут", "выбранн", "this", "here", "его "))
    if (screen["confidence"] < threshold or screen["ambiguity"]["level"] == "high"
            or (screen["ambiguity"]["level"] == "medium" and not screen.get("selected_object") and deictic)):
        result = clarify(screen, f"уверенность распознавания экрана {screen['confidence']:.2f} < {threshold}"
                                 if screen["confidence"] < threshold else "данные экрана неоднозначны")
    else:
        sel = screen.get("selected_object")
        # 2) сверка объекта с сетью расчёта: неверный объект хуже, чем уточняющий вопрос
        res = analytics.load_results(scenario_dir)
        selection = {"type": "whole_network", "id": None}
        if sel:
            oid = sel["id"]
            if oid in res.wn.node_name_list:
                selection = {"type": "node", "id": oid}
            elif oid in res.wn.link_name_list:
                selection = {"type": "link", "id": oid}
            else:
                result = clarify(screen, f"объект {oid} не найден в расчёте {scenario_dir.name}")
                result["network_objects_hint"] = (res.wn.node_name_list[:5] + res.wn.link_name_list[:5])
                if out:
                    _write(out, result)
                return result

        mode = mode_for(screen, question)
        ui = build_ui_block(screen, question)
        ctx = context_builder.build_context(scenario_dir, mode=mode, question=question,
                                            selection=selection, ui=ui)
        ctx["request"]["ui"]["mode_auto"] = mode
        result = {"action": "answer", "mode": mode, "llm_context": ctx}
        if out:
            _write(out, ctx)
        return result

    if out:
        _write(out, result)
    return result


def _write(out: str | Path, payload: dict) -> None:
    p = Path(out)
    if not p.is_absolute():
        p = common.ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Экран + расчёт → контекст для LLM (или уточняющий вопрос)")
    ap.add_argument("--screen", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--question", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    res = compose(args.screen, args.scenario, args.question, args.out)
    if res["action"] == "ask_user":
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        ctx = res["llm_context"]
        print(f"режим: {res['mode']}; ui: {json.dumps(ctx['request']['ui'], ensure_ascii=False)}")
        print(f"размер контекста: {ctx['_meta']['chars']} символов, фактов: {ctx['_meta']['evidence_count']}")


if __name__ == "__main__":
    main()
