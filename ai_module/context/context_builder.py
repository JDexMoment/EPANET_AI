from typing import Any, Dict, List, Optional, Tuple
from ai_module.analytics.engineering_engine import EngineeringAnalyticsEngine
from ai_module.analytics.scenario_comparator import ScenarioComparator
from ai_module.context.schemas import (
    AnalysisSchema,
    LLMContextPayload,
    NetworkSummarySchema,
    ProjectSchema,
    SelectionSchema,
)
from ai_module.engine_adapter.ctypes_epanet import EpanetEngineAdapter
from ai_module.knowledge_rag.knowledge_base import EngineeringKnowledgeBase


class ContextBuilder:
    """
    Context Collector + Prompt/Context Builder (Roadmap Section 4 & 5).
    Orchestrates C-engine simulation, deterministic analytics, viewport filtering,
    and RAG rule retrieval to build a compact, fact-grounded JSON payload for Qwen3.
    """

    def __init__(self):
        self.engine = EpanetEngineAdapter()
        self.analytics = EngineeringAnalyticsEngine()
        self.kb = EngineeringKnowledgeBase()

    def build_context(
        self,
        inp_file: str,
        mode: str = "what_happens",
        question: str = "",
        selected_type: str = "none",
        selected_id: str = "",
        target_period: int = 0,
        visible_nodes: Optional[List[str]] = None,
        visible_links: Optional[List[str]] = None,
        compare_inp_file: Optional[str] = None,
    ) -> Tuple[LLMContextPayload, Dict[str, Any], Dict[str, Any]]:
        sim_data = self.engine.run_simulation(inp_file, target_period=target_period)
        analytics_res = self.analytics.analyze(
            sim_data,
            selected_id=selected_id,
            visible_nodes=visible_nodes,
            visible_links=visible_links,
        )

        # Resolve selection schema
        focus_id = selected_id or analytics_res["focus_object_id"]
        focus_type = selected_type
        if focus_type in ("none", "") and analytics_res["selected_object_details"]:
            focus_type = analytics_res["selected_object_details"]["type"]

        # Optional scenario comparison
        scenario_diff = None
        if compare_inp_file:
            comp_sim = self.engine.run_simulation(compare_inp_file, target_period=target_period)
            comp_analytics = self.analytics.analyze(comp_sim)
            scenario_diff = ScenarioComparator.compare(sim_data, analytics_res, comp_sim, comp_analytics)

        rules = self.kb.retrieve_relevant_rules(analytics_res["top_alerts"], mode, question)

        payload = LLMContextPayload(
            project=ProjectSchema(
                name=sim_data["project"]["name"],
                scenario="comparison" if compare_inp_file else "current_screen",
                flow_units_native=sim_data["project"]["flow_units_native"],
                normalized_units=sim_data["project"]["normalized_units"],
            ),
            analysis=AnalysisSchema(
                type=sim_data["analysis"]["type"],
                duration_h=sim_data["analysis"]["duration_h"],
                step_h=sim_data["analysis"]["step_h"],
                active_period=sim_data["analysis"]["active_period"],
                active_time_h=sim_data["analysis"]["active_time_h"],
                status=sim_data["analysis"]["status"],
            ),
            selection=SelectionSchema(type=focus_type, id=focus_id),
            network_summary=NetworkSummarySchema(
                junctions=sim_data["network_summary"]["junctions"],
                pipes=sim_data["network_summary"]["pipes"],
                pumps=sim_data["network_summary"]["pumps"],
                tanks=sim_data["network_summary"]["tanks"],
                reservoirs=sim_data["network_summary"]["reservoirs"],
                valves=sim_data["network_summary"]["valves"],
            ),
            kpi=analytics_res["kpi"],
            alerts=analytics_res["top_alerts"],
            viewport_context=analytics_res["viewport_summary"],
            selected_object_details=analytics_res["selected_object_details"],
            topological_neighborhood=analytics_res["topological_neighborhood"],
            scenario_comparison=scenario_diff,
            applicable_rules=rules,
        )

        return payload, sim_data, analytics_res

    @staticmethod
    def split_for_dataset_storage(
        payload: LLMContextPayload,
        sim_data: Dict[str, Any],
        analytics_res: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Formats scenario into the 3 canonical JSON structures specified in Roadmap Section 9:
        1. project_context.json — параметры расчёта и состояние модели/экрана
        2. analysis_results.json — фактические результаты EPANET
        3. derived_metrics.json — рассчитанные аналитические признаки, KPI, аномалии и граф связей
        """
        project_context = {
            "project": payload.project.model_dump(),
            "analysis": payload.analysis.model_dump(),
            "selection": payload.selection.model_dump(),
            "network_summary": payload.network_summary.model_dump(),
            "viewport": {
                "is_zoomed_subregion": payload.viewport_context.get("is_zoomed_subregion", False),
                "visible_nodes_count": payload.viewport_context.get("visible_nodes_count", 0),
                "visible_links_count": payload.viewport_context.get("visible_links_count", 0),
            },
        }

        analysis_results = {
            "active_period": sim_data["analysis"]["active_period"],
            "active_time_h": sim_data["analysis"]["active_time_h"],
            "nodes": sim_data["active_snapshot"]["nodes"],
            "links": sim_data["active_snapshot"]["links"],
            "topology": sim_data["topology"],
        }

        derived_metrics = {
            "kpi": payload.kpi.model_dump(),
            "alerts": [a.model_dump() for a in payload.alerts],
            "selected_object_details": payload.selected_object_details,
            "topological_neighborhood": payload.topological_neighborhood,
            "scenario_comparison": payload.scenario_comparison,
        }

        return project_context, analysis_results, derived_metrics
