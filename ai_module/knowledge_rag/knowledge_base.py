import json
from typing import Any, Dict, List
from ai_module.config.settings import BASE_DIR
from ai_module.context.schemas import AlertItem


class EngineeringKnowledgeBase:
    """
    Knowledge / RAG Layer (Roadmap Section 4).
    Provides normative thresholds, interpretation rules, typical hydraulic causes,
    and report section templates based on detected anomaly types and user query.
    """

    def __init__(self):
        rules_file = BASE_DIR / "config" / "rules_and_norms.json"
        self.data = json.loads(rules_file.read_text(encoding="utf-8"))
        self.rules_by_category = {r["category"]: r for r in self.data.get("rules", [])}

    def retrieve_relevant_rules(self, alerts: List[AlertItem], mode: str, question: str = "") -> List[Dict[str, Any]]:
        categories = {a.type for a in alerts}
        q_lower = question.lower()
        if "давлен" in q_lower or "напор" in q_lower:
            categories.update(["low_pressure", "negative_pressure", "high_pressure"])
        if "скорост" in q_lower or "уклон" in q_lower or "потер" in q_lower or "труб" in q_lower:
            categories.update(["high_velocity", "high_headloss_gradient"])
        if "засто" in q_lower or "хлор" in q_lower or "возраст" in q_lower:
            categories.add("stagnation_zero_flow")

        if mode in ("generate_report", "find_problems") and not categories:
            # Return core pressure and velocity norms as baseline reference
            categories.update(["low_pressure", "high_velocity"])

        matched = [
            self.rules_by_category[cat]
            for cat in categories
            if cat in self.rules_by_category
        ]
        return matched

    def get_report_sections(self) -> List[str]:
        return self.data.get("report_template", {}).get("sections", [])
