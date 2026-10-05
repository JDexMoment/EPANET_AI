"""Считает derived_metrics.json + evidence.json + llm_context.json для всех сценариев манифеста.

Запуск:
    python -m src.generate.build_derived_all
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .. import analytics, common, context_builder


def main() -> None:
    ap = argparse.ArgumentParser(description="Аналитический слой по всем сценариям")
    ap.add_argument("--manifest", default="data/scenarios/manifest.jsonl")
    ap.add_argument("--only", default=None, help="scenario_id — обработать только один")
    ap.add_argument("--skip-context", action="store_true")
    ap.add_argument("--modes", default="whats_happening,make_report",
                    help="какие варианты контекста собрать заранее")
    args = ap.parse_args()

    manifest = common.read_jsonl(args.manifest)
    ok = err = 0
    for rec in manifest:
        if rec.get("status") != "ok":
            continue
        sid = rec["scenario_id"]
        if args.only and sid != args.only:
            continue
        sdir = common.ROOT / "data" / "scenarios" / sid
        scen = common.read_json(sdir / "scenario.json")
        baseline = common.ROOT / scen["baseline_ref"] if scen.get("baseline_ref") else None
        try:
            d = analytics.build_derived(sdir, baseline_dir=baseline)
            n_alerts = len([a for a in d["alerts"]])
            top = d["top_problems"][0] if d["top_problems"] else None
            print(f"{sid:46s} alerts={n_alerts:3d}  top={top['rule'] if top else '-':22s} "
                  f"obj={top['object'] if top else '-':8s} minP={d['kpi']['min_pressure_m']:6.1f} м")
            if not args.skip_context:
                for mode in args.modes.split(","):
                    ctx = context_builder.build_context(sdir, mode=mode)
                    common.write_json(sdir / "derived" / f"llm_context_{mode}.json", ctx)
            ok += 1
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"ОШИБКА {sid}: {e}")
    print(f"\nГотово: {ok} сценариев, ошибок: {err}")


if __name__ == "__main__":
    main()
