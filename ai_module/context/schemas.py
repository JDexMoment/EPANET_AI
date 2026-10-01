from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

AIModeLiteral = Literal[
    "what_happens",
    "explain_object",
    "find_problems",
    "why_happened",
    "generate_report",
    "compare_scenarios",
    "ask_question",
]


class ProjectSchema(BaseModel):
    name: str
    scenario: str = "baseline"
    flow_units_native: str = "LPS"
    normalized_units: str = "SI (m, L/s, m/s, mm)"


class AnalysisSchema(BaseModel):
    type: str = "extended_period"
    duration_h: float = 24.0
    step_h: float = 1.0
    active_period: int = 0
    active_time_h: float = 0.0
    status: str = "converged"


class SelectionSchema(BaseModel):
    type: str = "none"
    id: str = ""


class NetworkSummarySchema(BaseModel):
    junctions: int
    pipes: int
    pumps: int
    tanks: int
    reservoirs: int = 0
    valves: int = 0


class KPISchema(BaseModel):
    min_pressure_m: float
    min_pressure_node: str
    max_pressure_m: float
    max_pressure_node: str
    total_demand_lps: float
    max_velocity_mps: float
    max_velocity_pipe: str
    max_headloss_m_per_km: float
    max_headloss_pipe: str
    alerts_count: int


class AlertItem(BaseModel):
    type: str = Field(..., description="Category: low_pressure, negative_pressure, high_pressure, high_velocity, high_headloss_gradient, stagnation_zero_flow")
    severity: Literal["critical", "warning", "info"] = "warning"
    object_type: str = "junction"
    object: str = Field(..., description="Object ID, e.g. J-104 or P-881")
    metric_name: str
    value: float
    threshold: float
    unit: str
    description: str


class LLMContextPayload(BaseModel):
    """
    Machine-readable intermediate context sent to Qwen3 (Roadmap Section 5).
    Prevents sending huge raw INP/CSV files while preserving 100% of engineering facts.
    """
    project: ProjectSchema
    analysis: AnalysisSchema
    selection: SelectionSchema
    network_summary: NetworkSummarySchema
    kpi: KPISchema
    alerts: List[AlertItem]
    viewport_context: Dict[str, Any] = Field(default_factory=dict)
    selected_object_details: Optional[Dict[str, Any]] = None
    topological_neighborhood: Optional[Dict[str, Any]] = None
    scenario_comparison: Optional[Dict[str, Any]] = None
    applicable_rules: List[Dict[str, Any]] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    mode: AIModeLiteral = "what_happens"
    question: str = ""
    inp_file: str
    compare_inp_file: Optional[str] = None
    screenshot_file: Optional[str] = None
    project: Optional[Dict[str, Any]] = None
    simulation_state: Optional[Dict[str, Any]] = None
    selection: Optional[Dict[str, Any]] = None
    viewport: Optional[Dict[str, Any]] = None


class AnalyzeResponse(BaseModel):
    mode: AIModeLiteral
    question: str
    answer: str
    structured_context: LLMContextPayload
    evidence: List[Dict[str, Any]]
    severity: str
    category: str
    report_path: Optional[str] = None
    backend_used: str
    latency_ms: float
