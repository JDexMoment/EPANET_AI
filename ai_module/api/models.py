from typing import Any, Dict, Optional
from pydantic import BaseModel

from ai_module.context.schemas import AIModeLiteral, LLMContextPayload


class HealthResponse(BaseModel):
    status: str
    service: str
    llm_backend: str
    active_model: str
    epanet_engine: str


class AnalyzeRequest(BaseModel):
    """Payload posted by the Delphi `Uai_bridge.pas` unit on every AI button click."""
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
    evidence: list[Dict[str, Any]]
    severity: str
    category: str
    report_path: Optional[str] = None
    backend_used: str
    latency_ms: float


class ContextResponse(BaseModel):
    structured_context: LLMContextPayload
