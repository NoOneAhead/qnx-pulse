"""FastAPI backend for QNX-Pulse Studio (REST API + Web UI + Codelab preview)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from qnx_pulse import __version__
from qnx_pulse.analyzers import (
    analyze_trace,
    audit_security_and_boot,
    diagnose_with_copilot,
    generate_compliance_report,
)
from qnx_pulse.datasets import list_scenarios, load_scenario
from qnx_pulse.models import (
    AnalyzeRequest,
    AuditRequest,
    ComplianceReportRequest,
    CopilotRequest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
CODELAB_DIR = REPO_ROOT / "codelab"

app = FastAPI(
    title="QNX-Pulse Studio API",
    description="QNX 8.0 Microkernel Trace, IPC Topology, Buildfile & Secpol Studio",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "qnx-pulse",
        "version": __version__,
        "target_rtos": "QNX SDP 8.0",
        "scenarios_available": len(list_scenarios()),
    }


@app.get("/api/scenarios")
def api_list_scenarios() -> dict[str, Any]:
    return {"scenarios": list_scenarios()}


@app.get("/api/scenarios/{scenario_id}")
def api_get_scenario(scenario_id: str) -> dict[str, Any]:
    data = load_scenario(scenario_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")

    meta = data["meta"]
    trace_analysis = analyze_trace(
        trace_text=data["trace_text"],
        slog2_text=data["slog2_text"],
        scenario_id=meta["id"],
        scenario_name=meta["name"],
        description=meta.get("description", ""),
    )
    audit_result = audit_security_and_boot(
        buildfile_text=data["buildfile_text"],
        secpol_text=data["secpol_text"],
    )
    copilot = diagnose_with_copilot(
        question="",
        trace_result=trace_analysis,
        audit_result=audit_result,
    )
    return {
        "meta": meta,
        "artifacts": {
            "trace_text": data["trace_text"],
            "slog2_text": data["slog2_text"],
            "buildfile_text": data["buildfile_text"],
            "secpol_text": data["secpol_text"],
        },
        "trace_analysis": trace_analysis.model_dump(),
        "audit_result": audit_result.model_dump(),
        "copilot": copilot.model_dump(),
    }


@app.post("/api/analyze/trace")
def api_analyze_trace(req: AnalyzeRequest) -> dict[str, Any]:
    if not req.trace_text.strip():
        raise HTTPException(status_code=400, detail="trace_text must not be empty")
    result = analyze_trace(
        trace_text=req.trace_text,
        slog2_text=req.slog2_text,
        scenario_id=req.scenario_id,
        scenario_name=req.scenario_name,
        description=req.description,
    )
    return result.model_dump()


@app.post("/api/audit/security-boot")
def api_audit_security_boot(req: AuditRequest) -> dict[str, Any]:
    if not req.buildfile_text.strip() and not req.secpol_text.strip():
        raise HTTPException(status_code=400, detail="Provide buildfile_text and/or secpol_text")
    result = audit_security_and_boot(
        buildfile_text=req.buildfile_text,
        secpol_text=req.secpol_text,
    )
    return result.model_dump()


@app.post("/api/copilot/diagnose")
def api_copilot_diagnose(req: CopilotRequest) -> dict[str, Any]:
    trace_text = req.trace_text or ""
    slog2_text = req.slog2_text or ""
    buildfile_text = req.buildfile_text or ""
    secpol_text = req.secpol_text or ""
    scenario_id = req.scenario_id or "custom"
    scenario_name = "Custom Trace"

    if req.scenario_id and not (trace_text or buildfile_text or secpol_text):
        data = load_scenario(req.scenario_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Scenario '{req.scenario_id}' not found")
        trace_text = data["trace_text"]
        slog2_text = data["slog2_text"]
        buildfile_text = data["buildfile_text"]
        secpol_text = data["secpol_text"]
        scenario_name = data["meta"]["name"]

    trace_res = (
        analyze_trace(trace_text, slog2_text, scenario_id=scenario_id, scenario_name=scenario_name)
        if trace_text.strip()
        else None
    )
    audit_res = (
        audit_security_and_boot(buildfile_text, secpol_text)
        if (buildfile_text.strip() or secpol_text.strip())
        else None
    )
    diagnosis = diagnose_with_copilot(
        question=req.question,
        trace_result=trace_res,
        audit_result=audit_res,
        llm_provider=req.llm_provider,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
        llm_base_url=req.llm_base_url,
    )
    return diagnosis.model_dump()


@app.post("/api/reports/compliance")
def api_compliance_report(req: ComplianceReportRequest) -> Response:
    trace_text = req.trace_text or ""
    slog2_text = req.slog2_text or ""
    buildfile_text = req.buildfile_text or ""
    secpol_text = req.secpol_text or ""
    scenario_id = req.scenario_id or "custom"
    scenario_name = "Custom Trace"

    if req.scenario_id and not (trace_text or buildfile_text or secpol_text):
        data = load_scenario(req.scenario_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Scenario '{req.scenario_id}' not found")
        trace_text = data["trace_text"]
        slog2_text = data["slog2_text"]
        buildfile_text = data["buildfile_text"]
        secpol_text = data["secpol_text"]
        scenario_name = data["meta"]["name"]

    trace_res = (
        analyze_trace(trace_text, slog2_text, scenario_id=scenario_id, scenario_name=scenario_name)
        if trace_text.strip()
        else None
    )
    audit_res = (
        audit_security_and_boot(buildfile_text, secpol_text)
        if (buildfile_text.strip() or secpol_text.strip())
        else None
    )

    content = generate_compliance_report(
        trace_result=trace_res,
        audit_result=audit_res,
        standard=req.standard,
        fmt=req.format,
    )
    media = "application/json" if req.format == "json" else "text/markdown; charset=utf-8"
    return PlainTextResponse(content=content, media_type=media)


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon() -> Response:
    return Response(status_code=204)


@app.get("/")
def serve_index() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Web UI not found")
    return FileResponse(index)


if CODELAB_DIR.exists():
    app.mount("/codelab", StaticFiles(directory=str(CODELAB_DIR), html=True), name="codelab")

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
