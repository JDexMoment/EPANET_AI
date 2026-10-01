from typing import Any, Dict, List


class ScenarioComparator:
    """
    Deterministic comparison of two EPANET calculations (Roadmap Section 2 & 4: «Сравнить сценарии»).
    Computes exact deltas for KPIs, node pressures, link flows/velocities, and topology/parameter changes.
    """

    @staticmethod
    def compare(
        base_sim: Dict[str, Any],
        base_analytics: Dict[str, Any],
        comp_sim: Dict[str, Any],
        comp_analytics: Dict[str, Any],
    ) -> Dict[str, Any]:
        base_kpi = base_analytics["kpi"]
        comp_kpi = comp_analytics["kpi"]

        kpi_deltas = {
            "min_pressure_m_before": base_kpi.min_pressure_m,
            "min_pressure_m_after": comp_kpi.min_pressure_m,
            "min_pressure_delta_m": round(comp_kpi.min_pressure_m - base_kpi.min_pressure_m, 2),
            "max_pressure_m_before": base_kpi.max_pressure_m,
            "max_pressure_m_after": comp_kpi.max_pressure_m,
            "max_pressure_delta_m": round(comp_kpi.max_pressure_m - base_kpi.max_pressure_m, 2),
            "max_velocity_mps_before": base_kpi.max_velocity_mps,
            "max_velocity_mps_after": comp_kpi.max_velocity_mps,
            "max_velocity_delta_mps": round(comp_kpi.max_velocity_mps - base_kpi.max_velocity_mps, 2),
            "alerts_count_before": base_kpi.alerts_count,
            "alerts_count_after": comp_kpi.alerts_count,
            "alerts_count_delta": comp_kpi.alerts_count - base_kpi.alerts_count,
        }

        # Parameter differences in links (e.g. diameter, roughness, status changes)
        base_links_meta = {l["id"]: l for l in base_sim["topology"]["links"]}
        comp_links_meta = {l["id"]: l for l in comp_sim["topology"]["links"]}
        base_links_state = base_sim["active_snapshot"]["links"]
        comp_links_state = comp_sim["active_snapshot"]["links"]

        modified_parameters: List[Dict[str, Any]] = []
        for lid, b_meta in base_links_meta.items():
            if lid not in comp_links_meta:
                continue
            c_meta = comp_links_meta[lid]
            if b_meta["diameter_mm"] != c_meta["diameter_mm"]:
                modified_parameters.append({
                    "object": lid,
                    "parameter": "diameter_mm",
                    "before": b_meta["diameter_mm"],
                    "after": c_meta["diameter_mm"],
                })
            if b_meta["roughness"] != c_meta["roughness"]:
                modified_parameters.append({
                    "object": lid,
                    "parameter": "roughness",
                    "before": b_meta["roughness"],
                    "after": c_meta["roughness"],
                })
            b_st = base_links_state.get(lid, {}).get("status", "OPEN")
            c_st = comp_links_state.get(lid, {}).get("status", "OPEN")
            if b_st != c_st:
                modified_parameters.append({
                    "object": lid,
                    "parameter": "status",
                    "before": b_st,
                    "after": c_st,
                })

        # Top node pressure changes
        base_nodes_state = base_sim["active_snapshot"]["nodes"]
        comp_nodes_state = comp_sim["active_snapshot"]["nodes"]
        node_diffs: List[Dict[str, Any]] = []
        for nid, b_st in base_nodes_state.items():
            if nid in comp_nodes_state:
                c_st = comp_nodes_state[nid]
                dp = round(c_st["pressure_m"] - b_st["pressure_m"], 2)
                if abs(dp) >= 0.1:
                    node_diffs.append({
                        "node_id": nid,
                        "pressure_before_m": b_st["pressure_m"],
                        "pressure_after_m": c_st["pressure_m"],
                        "delta_pressure_m": dp,
                    })
        node_diffs.sort(key=lambda x: -abs(x["delta_pressure_m"]))

        # Top link velocity/flow changes
        link_diffs: List[Dict[str, Any]] = []
        for lid, b_st in base_links_state.items():
            if lid in comp_links_state:
                c_st = comp_links_state[lid]
                dv = round(c_st["velocity_mps"] - b_st["velocity_mps"], 2)
                df = round(c_st["flow_lps"] - b_st["flow_lps"], 2)
                if abs(dv) >= 0.05 or abs(df) >= 0.5:
                    link_diffs.append({
                        "link_id": lid,
                        "flow_before_lps": b_st["flow_lps"],
                        "flow_after_lps": c_st["flow_lps"],
                        "delta_flow_lps": df,
                        "velocity_before_mps": b_st["velocity_mps"],
                        "velocity_after_mps": c_st["velocity_mps"],
                        "delta_velocity_mps": dv,
                    })
        link_diffs.sort(key=lambda x: -abs(x["delta_flow_lps"]))

        return {
            "baseline_scenario": base_sim["project"]["name"],
            "compared_scenario": comp_sim["project"]["name"],
            "kpi_deltas": kpi_deltas,
            "modified_parameters": modified_parameters,
            "top_node_pressure_changes": node_diffs[:10],
            "top_link_flow_changes": link_diffs[:10],
        }
