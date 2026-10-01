from typing import Any, Dict, List, Optional, Set
from ai_module.config.settings import DEFAULT_THRESHOLDS
from ai_module.context.schemas import AlertItem, KPISchema


class EngineeringAnalyticsEngine:
    """
    Deterministic Engineering Analytics Layer (Roadmap Section 4 & 8).
    Computes all numerical KPIs, threshold alerts, topological causes, and time peaks
    so the LLM never has to guess or perform raw arithmetic.
    """

    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def analyze(
        self,
        sim_data: Dict[str, Any],
        selected_id: str = "",
        visible_nodes: Optional[List[str]] = None,
        visible_links: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        nodes_meta = {n["id"]: n for n in sim_data["topology"]["nodes"]}
        links_meta = {l["id"]: l for l in sim_data["topology"]["links"]}
        active_snap = sim_data["active_snapshot"]
        node_states = active_snap["nodes"]
        link_states = active_snap["links"]

        # 1. Compute KPIs across junctions (for pressure) and pipes (for velocity/headloss)
        junc_pressures = {
            nid: state["pressure_m"]
            for nid, state in node_states.items()
            if nodes_meta.get(nid, {}).get("type") == "junction"
        }
        if not junc_pressures:
            junc_pressures = {nid: st["pressure_m"] for nid, st in node_states.items()}

        min_p_node = min(junc_pressures, key=junc_pressures.get)
        max_p_node = max(junc_pressures, key=junc_pressures.get)
        min_p_val = round(junc_pressures[min_p_node], 3)
        max_p_val = round(junc_pressures[max_p_node], 3)

        total_demand = round(
            sum(
                st["demand_lps"]
                for nid, st in node_states.items()
                if nodes_meta.get(nid, {}).get("type") == "junction" and st["demand_lps"] > 0
            ),
            3,
        )

        pipe_velocities = {
            lid: st["velocity_mps"]
            for lid, st in link_states.items()
            if "pipe" in links_meta.get(lid, {}).get("type", "pipe")
        }
        if not pipe_velocities:
            pipe_velocities = {lid: st["velocity_mps"] for lid, st in link_states.items()}

        max_v_pipe = max(pipe_velocities, key=pipe_velocities.get)
        max_v_val = round(pipe_velocities[max_v_pipe], 3)

        pipe_headlosses = {
            lid: st["headloss_m_per_km"]
            for lid, st in link_states.items()
            if "pipe" in links_meta.get(lid, {}).get("type", "pipe")
        }
        if not pipe_headlosses:
            pipe_headlosses = {lid: 0.0 for lid in link_states}

        max_hl_pipe = max(pipe_headlosses, key=pipe_headlosses.get)
        max_hl_val = round(pipe_headlosses[max_hl_pipe], 3)

        # 2. Detect anomalies (Alerts)
        alerts: List[AlertItem] = []
        vis_node_set: Optional[Set[str]] = set(visible_nodes) if visible_nodes else None
        vis_link_set: Optional[Set[str]] = set(visible_links) if visible_links else None

        for nid, st in node_states.items():
            ntype = nodes_meta.get(nid, {}).get("type", "junction")
            if ntype != "junction":
                continue
            p = st["pressure_m"]
            if p < self.thresholds["negative_pressure_m"]:
                alerts.append(
                    AlertItem(
                        type="negative_pressure",
                        severity="critical",
                        object_type="junction",
                        object=nid,
                        metric_name="pressure_m",
                        value=round(p, 2),
                        threshold=self.thresholds["negative_pressure_m"],
                        unit="m",
                        description=f"Отрицательное давление (вакуум) в узле {nid}: {p:.2f} м (< 0 м)",
                    )
                )
            elif p < self.thresholds["min_pressure_critical_m"]:
                alerts.append(
                    AlertItem(
                        type="low_pressure",
                        severity="critical",
                        object_type="junction",
                        object=nid,
                        metric_name="pressure_m",
                        value=round(p, 2),
                        threshold=self.thresholds["min_pressure_critical_m"],
                        unit="m",
                        description=f"Критически низкий напор в узле {nid}: {p:.2f} м (< {self.thresholds['min_pressure_critical_m']} м)",
                    )
                )
            elif p < self.thresholds["min_pressure_warning_m"]:
                alerts.append(
                    AlertItem(
                        type="low_pressure",
                        severity="warning",
                        object_type="junction",
                        object=nid,
                        metric_name="pressure_m",
                        value=round(p, 2),
                        threshold=self.thresholds["min_pressure_warning_m"],
                        unit="m",
                        description=f"Пониженный свободный напор в узле {nid}: {p:.2f} м (< {self.thresholds['min_pressure_warning_m']} м)",
                    )
                )
            elif p > self.thresholds["max_pressure_critical_m"]:
                alerts.append(
                    AlertItem(
                        type="high_pressure",
                        severity="critical",
                        object_type="junction",
                        object=nid,
                        metric_name="pressure_m",
                        value=round(p, 2),
                        threshold=self.thresholds["max_pressure_critical_m"],
                        unit="m",
                        description=f"Критически высокое давление в узле {nid}: {p:.2f} м (> {self.thresholds['max_pressure_critical_m']} м)",
                    )
                )
            elif p > self.thresholds["max_pressure_warning_m"]:
                alerts.append(
                    AlertItem(
                        type="high_pressure",
                        severity="warning",
                        object_type="junction",
                        object=nid,
                        metric_name="pressure_m",
                        value=round(p, 2),
                        threshold=self.thresholds["max_pressure_warning_m"],
                        unit="m",
                        description=f"Избыточное давление в узле {nid}: {p:.2f} м (> {self.thresholds['max_pressure_warning_m']} м)",
                    )
                )

        for lid, st in link_states.items():
            lmeta = links_meta.get(lid, {})
            ltype = lmeta.get("type", "pipe")
            v = st["velocity_mps"]
            hl = st["headloss_m_per_km"]
            status = st["status"]

            if "pipe" in ltype:
                if v > self.thresholds["max_velocity_critical_mps"]:
                    alerts.append(
                        AlertItem(
                            type="high_velocity",
                            severity="critical",
                            object_type="pipe",
                            object=lid,
                            metric_name="velocity_mps",
                            value=round(v, 2),
                            threshold=self.thresholds["max_velocity_critical_mps"],
                            unit="m/s",
                            description=f"Критическая скорость потока в трубе {lid}: {v:.2f} м/с (> {self.thresholds['max_velocity_critical_mps']} м/с)",
                        )
                    )
                elif v > self.thresholds["max_velocity_warning_mps"]:
                    alerts.append(
                        AlertItem(
                            type="high_velocity",
                            severity="warning",
                            object_type="pipe",
                            object=lid,
                            metric_name="velocity_mps",
                            value=round(v, 2),
                            threshold=self.thresholds["max_velocity_warning_mps"],
                            unit="m/s",
                            description=f"Повышенная скорость потока в трубе {lid}: {v:.2f} м/с (> {self.thresholds['max_velocity_warning_mps']} м/с)",
                        )
                    )

                if hl > self.thresholds["max_headloss_m_per_km"]:
                    alerts.append(
                        AlertItem(
                            type="high_headloss_gradient",
                            severity="warning",
                            object_type="pipe",
                            object=lid,
                            metric_name="headloss_m_per_km",
                            value=round(hl, 2),
                            threshold=self.thresholds["max_headloss_m_per_km"],
                            unit="m/km",
                            description=f"Высокий гидравлический уклон в трубе {lid}: {hl:.2f} м/км (> {self.thresholds['max_headloss_m_per_km']} м/км)",
                        )
                    )

                if status == "OPEN" and abs(v) < self.thresholds["min_velocity_stagnation_mps"]:
                    alerts.append(
                        AlertItem(
                            type="stagnation_zero_flow",
                            severity="info",
                            object_type="pipe",
                            object=lid,
                            metric_name="velocity_mps",
                            value=round(v, 3),
                            threshold=self.thresholds["min_velocity_stagnation_mps"],
                            unit="m/s",
                            description=f"Зона застоя / околонулевой скорости в трубе {lid}: {v:.3f} м/с",
                        )
                    )

        # Sort alerts: critical first, then warning, then info; prioritize visible viewport objects
        sev_rank = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(
            key=lambda a: (
                sev_rank.get(a.severity, 3),
                0 if (vis_node_set and a.object in vis_node_set) or (vis_link_set and a.object in vis_link_set) else 1,
                -abs(a.value),
            )
        )

        kpi = KPISchema(
            min_pressure_m=min_p_val,
            min_pressure_node=min_p_node,
            max_pressure_m=max_p_val,
            max_pressure_node=max_p_node,
            total_demand_lps=total_demand,
            max_velocity_mps=max_v_val,
            max_velocity_pipe=max_v_pipe,
            max_headloss_m_per_km=max_hl_val,
            max_headloss_pipe=max_hl_pipe,
            alerts_count=len(alerts),
        )

        # 3. Determine focus object (either explicitly selected by user or top alert object)
        focus_id = selected_id
        if not focus_id and alerts:
            focus_id = alerts[0].object
        elif not focus_id:
            focus_id = min_p_node

        selected_details = self._extract_object_details(focus_id, nodes_meta, links_meta, node_states, link_states, sim_data["all_snapshots"])
        neighborhood = self._trace_neighborhood(focus_id, nodes_meta, links_meta, node_states, link_states)

        # 4. Viewport summary (what is visible on user's zoomed screen)
        viewport_summary = self._build_viewport_summary(
            vis_node_set, vis_link_set, nodes_meta, links_meta, node_states, link_states, alerts
        )

        return {
            "kpi": kpi,
            "alerts": alerts,
            "top_alerts": alerts[: int(self.thresholds["top_n_alerts"])],
            "focus_object_id": focus_id,
            "selected_object_details": selected_details,
            "topological_neighborhood": neighborhood,
            "viewport_summary": viewport_summary,
        }

    def _extract_object_details(
        self,
        obj_id: str,
        nodes_meta: Dict[str, Any],
        links_meta: Dict[str, Any],
        node_states: Dict[str, Any],
        link_states: Dict[str, Any],
        all_snapshots: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if obj_id in nodes_meta:
            meta = nodes_meta[obj_id]
            state = node_states.get(obj_id, {})
            # Temporal min/max across 24h simulation
            p_series = [s["nodes"][obj_id]["pressure_m"] for s in all_snapshots if obj_id in s["nodes"]]
            d_series = [s["nodes"][obj_id]["demand_lps"] for s in all_snapshots if obj_id in s["nodes"]]
            return {
                "object_class": "node",
                "id": obj_id,
                "type": meta["type"],
                "elevation_m": meta["elevation_m"],
                "base_demand_lps": meta["base_demand_lps"],
                "current_state": state,
                "time_series_summary": {
                    "min_pressure_m": round(min(p_series), 2) if p_series else state.get("pressure_m", 0.0),
                    "max_pressure_m": round(max(p_series), 2) if p_series else state.get("pressure_m", 0.0),
                    "max_demand_lps": round(max(d_series), 2) if d_series else state.get("demand_lps", 0.0),
                },
            }
        if obj_id in links_meta:
            meta = links_meta[obj_id]
            state = link_states.get(obj_id, {})
            v_series = [s["links"][obj_id]["velocity_mps"] for s in all_snapshots if obj_id in s["links"]]
            f_series = [s["links"][obj_id]["flow_lps"] for s in all_snapshots if obj_id in s["links"]]
            reverse_flow_hours = sum(1 for f in f_series if f < -1e-4)
            return {
                "object_class": "link",
                "id": obj_id,
                "type": meta["type"],
                "from_node": meta["from_node"],
                "to_node": meta["to_node"],
                "diameter_mm": meta["diameter_mm"],
                "length_m": meta["length_m"],
                "roughness": meta["roughness"],
                "current_state": state,
                "time_series_summary": {
                    "max_velocity_mps": round(max(v_series), 2) if v_series else state.get("velocity_mps", 0.0),
                    "max_abs_flow_lps": round(max((abs(x) for x in f_series), default=0.0), 2),
                    "reverse_flow_periods": reverse_flow_hours,
                },
            }
        return None

    def _trace_neighborhood(
        self,
        obj_id: str,
        nodes_meta: Dict[str, Any],
        links_meta: Dict[str, Any],
        node_states: Dict[str, Any],
        link_states: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Traces connected links and adjacent nodes around `obj_id`, determining actual flow
        direction (inflow vs outflow) based on the sign of `flow_lps`.
        """
        target_nodes: Set[str] = set()
        if obj_id in nodes_meta:
            target_nodes.add(obj_id)
        elif obj_id in links_meta:
            target_nodes.add(links_meta[obj_id]["from_node"])
            target_nodes.add(links_meta[obj_id]["to_node"])

        connected_links: List[Dict[str, Any]] = []
        neighbor_nodes: Dict[str, Any] = {}

        for lid, lmeta in links_meta.items():
            u, v = lmeta["from_node"], lmeta["to_node"]
            if u in target_nodes or v in target_nodes:
                lstate = link_states.get(lid, {})
                flow = lstate.get("flow_lps", 0.0)
                actual_from = u if flow >= 0 else v
                actual_to = v if flow >= 0 else u
                connected_links.append({
                    "link_id": lid,
                    "type": lmeta["type"],
                    "actual_flow_from": actual_from,
                    "actual_flow_to": actual_to,
                    "diameter_mm": lmeta["diameter_mm"],
                    "length_m": lmeta["length_m"],
                    "flow_lps": abs(flow),
                    "velocity_mps": lstate.get("velocity_mps", 0.0),
                    "headloss_m_per_km": lstate.get("headloss_m_per_km", 0.0),
                    "total_headloss_m": round(lstate.get("headloss_m_per_km", 0.0) * (lmeta["length_m"] / 1000.0), 2),
                    "status": lstate.get("status", "OPEN"),
                })
                for nid in (u, v):
                    if nid in nodes_meta:
                        neighbor_nodes[nid] = {
                            "type": nodes_meta[nid]["type"],
                            "elevation_m": nodes_meta[nid]["elevation_m"],
                            "head_m": node_states[nid]["head_m"],
                            "pressure_m": node_states[nid]["pressure_m"],
                            "demand_lps": node_states[nid]["demand_lps"],
                        }

        # Sort connected links by total headloss descending to immediately highlight hydraulic bottlenecks
        connected_links.sort(key=lambda x: -x["total_headloss_m"])
        return {
            "focus_object": obj_id,
            "connected_links": connected_links[:12],
            "adjacent_nodes": neighbor_nodes,
        }

    def _build_viewport_summary(
        self,
        vis_node_set: Optional[Set[str]],
        vis_link_set: Optional[Set[str]],
        nodes_meta: Dict[str, Any],
        links_meta: Dict[str, Any],
        node_states: Dict[str, Any],
        link_states: Dict[str, Any],
        all_alerts: List[AlertItem],
    ) -> Dict[str, Any]:
        if not vis_node_set and not vis_link_set:
            # Whole network is visible
            vis_node_set = set(nodes_meta.keys())
            vis_link_set = set(links_meta.keys())
            is_zoomed = False
        else:
            is_zoomed = (len(vis_node_set or set()) < len(nodes_meta))

        vis_nodes_list = [nid for nid in (vis_node_set or set()) if nid in node_states]
        vis_links_list = [lid for lid in (vis_link_set or set()) if lid in link_states]

        vis_alerts = [
            a.model_dump()
            for a in all_alerts
            if a.object in (vis_node_set or set()) or a.object in (vis_link_set or set())
        ]

        # Summarize visible objects compactly (cap at 25 nodes / 25 links for LLM prompt)
        nodes_sample = [
            {
                "id": nid,
                "type": nodes_meta[nid]["type"],
                "elev_m": nodes_meta[nid]["elevation_m"],
                "pressure_m": node_states[nid]["pressure_m"],
                "head_m": node_states[nid]["head_m"],
                "demand_lps": node_states[nid]["demand_lps"],
            }
            for nid in sorted(vis_nodes_list, key=lambda k: node_states[k]["pressure_m"])[:25]
        ]

        links_sample = [
            {
                "id": lid,
                "type": links_meta[lid]["type"],
                "from": links_meta[lid]["from_node"],
                "to": links_meta[lid]["to_node"],
                "diam_mm": links_meta[lid]["diameter_mm"],
                "flow_lps": link_states[lid]["flow_lps"],
                "vel_mps": link_states[lid]["velocity_mps"],
                "headloss_m_km": link_states[lid]["headloss_m_per_km"],
                "status": link_states[lid]["status"],
            }
            for lid in sorted(vis_links_list, key=lambda k: -link_states[k]["headloss_m_per_km"])[:25]
        ]

        return {
            "is_zoomed_subregion": is_zoomed,
            "visible_nodes_count": len(vis_nodes_list),
            "visible_links_count": len(vis_links_list),
            "visible_alerts_count": len(vis_alerts),
            "visible_nodes_data": nodes_sample,
            "visible_links_data": links_sample,
        }
