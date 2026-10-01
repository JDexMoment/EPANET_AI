"""
EPANET 2.2 Local AI & Engineering Analytics Service.

Run:
    uvicorn ai_module.api.app:app --host 127.0.0.1 --port 8765

Endpoints:
    GET  /api/v1/health            — service + LLM backend health check
    POST /api/v1/analyze           — full Data-first analysis (Delphi UI button)
    POST /api/v1/context           — build deterministic context only (debug)
    POST /api/v1/report            — generate engineering report only

The Delphi `Uai_bridge.pas` unit posts to `/api/v1/analyze`.
"""

import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ai_module.api.models import AnalyzeRequest, AnalyzeResponse, ContextResponse, HealthResponse
from ai_module.context.context_builder import ContextBuilder
from ai_module.llm.qwen_client import LocalQwenClient
from ai_module.reports.report_generator import ReportGenerator

app = FastAPI(
    title="EPANET 2.2 Local AI & Engineering Analytics Service",
    version="0.1.0",
    description="Data-first deterministic analytics + Qwen3 local LLM interpretation for EPANET 2.2",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_context_builder: Optional[ContextBuilder] = None
_qwen_client: Optional[LocalQwenClient] = None


def get_context_builder() -> ContextBuilder:
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilder()
    return _context_builder


def get_qwen_client() -> LocalQwenClient:
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = LocalQwenClient()
    return _qwen_client


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from ai_module.config.settings import LLM_BACKEND, LLM_MODEL_NAME, OLLAMA_MODEL_NAME

    backend = LLM_BACKEND
    active_model = OLLAMA_MODEL_NAME if backend in ("ollama", "openai_compat", "auto") else LLM_MODEL_NAME
    return HealthResponse(
        status="ok",
        service="epanet-ai",
        llm_backend=backend,
        active_model=active_model,
        epanet_engine="ctypes:libepanet2.so",
    )


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        cb = get_context_builder()
        payload, sim_data, analytics_res = cb.build_context(
            inp_file=req.inp_file,
            mode=req.mode,
            question=req.question,
            selected_type=(req.selection or {}).get("type", "none"),
            selected_id=(req.selection or {}).get("id", ""),
            target_period=int((req.simulation_state or {}).get("current_period", 0) or 0),
            visible_nodes=(req.viewport or {}).get("visible_nodes") if req.viewport else None,
            visible_links=(req.viewport or {}).get("visible_links") if req.viewport else None,
            compare_inp_file=req.compare_inp_file,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Analytics/Simulation error: {e}")

    client = get_qwen_client()
    answer, backend_used, latency_ms = client.generate(payload, req.mode, req.question)

    # Evidence payload — strictly deterministic facts used to ground the answer
    evidence: list[dict[str, Any]] = []
    for a in payload.alerts[:10]:
        evidence.append(
            {
                "object": a.object,
                "object_type": a.object_type,
                "metric": a.metric_name,
                "value": a.value,
                "unit": a.unit,
                "threshold": a.threshold,
                "severity": a.severity,
            }
        )
    if payload.selected_object_details:
        evidence.append(
            {
                "object": payload.selected_object_details.get("id"),
                "object_type": payload.selected_object_details.get("object_class"),
                "metrics": payload.selected_object_details.get("current_state", {}),
            }
        )

    report_path: Optional[str] = None
    if req.mode == "generate_report":
        try:
            md_path, html_path = ReportGenerator.save_report(payload, answer)
            report_path = md_path
        except Exception:
            report_path = None

    if payload.alerts:
        top_severity = payload.alerts[0].severity
        top_category = payload.alerts[0].type
    else:
        top_severity = "normal"
        top_category = "normal_operation"

    return AnalyzeResponse(
        mode=req.mode,
        question=req.question,
        answer=answer,
        structured_context=payload,
        evidence=evidence,
        severity=top_severity,
        category=top_category,
        report_path=report_path,
        backend_used=backend_used,
        latency_ms=latency_ms,
    )


@app.post("/api/v1/context", response_model=ContextResponse)
def context_only(req: AnalyzeRequest) -> ContextResponse:
    try:
        cb = get_context_builder()
        payload, _sim, _an = cb.build_context(
            inp_file=req.inp_file,
            mode=req.mode,
            question=req.question,
            selected_type=(req.selection or {}).get("type", "none"),
            selected_id=(req.selection or {}).get("id", ""),
            target_period=int((req.simulation_state or {}).get("current_period", 0) or 0),
            visible_nodes=(req.viewport or {}).get("visible_nodes") if req.viewport else None,
            visible_links=(req.viewport or {}).get("visible_links") if req.viewport else None,
            compare_inp_file=req.compare_inp_file,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ContextResponse(structured_context=payload)


@app.post("/api/v1/report")
def report_only(req: AnalyzeRequest) -> Dict[str, Any]:
    try:
        cb = get_context_builder()
        payload, _sim, _an = cb.build_context(
            inp_file=req.inp_file,
            mode="generate_report",
            question=req.question,
            selected_type=(req.selection or {}).get("type", "none"),
            selected_id=(req.selection or {}).get("id", ""),
            target_period=int((req.simulation_state or {}).get("current_period", 0) or 0),
            compare_inp_file=req.compare_inp_file,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    client = get_qwen_client()
    answer, backend_used, latency_ms = client.generate(payload, "generate_report", req.question)
    md_path, html_path = ReportGenerator.save_report(payload, answer)
    return {
        "report_markdown": md_path,
        "report_html": html_path,
        "answer": answer,
        "backend_used": backend_used,
        "latency_ms": latency_ms,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
