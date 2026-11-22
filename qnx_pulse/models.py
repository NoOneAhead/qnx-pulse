"""Pydantic data models for QNX-Pulse parsers, real-time analyzers, security auditors, and API."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class TraceHeader(BaseModel):
    file_name: str = "unknown.kev"
    sysname: str = "QNX"
    sys_release: str = "8.0.0"
    machine: str = "x86_64"
    nodename: str = "qnx8-target"
    cpu_num: int = 4
    cycles_per_sec: int = 2_500_000_000
    boot_date: str = ""
    trace_date: str = ""
    tracelogger_args: str = ""


class TraceEvent(BaseModel):
    seq: int
    timestamp_us: float
    raw_time: str
    cpu: int
    event_class: str
    subevent: str
    pid: Optional[int] = None
    tid: Optional[int] = None
    priority: Optional[int] = None
    policy: Optional[str] = None
    params: dict[str, str] = Field(default_factory=dict)
    raw_line: str = ""


class Slog2Entry(BaseModel):
    timestamp_str: str
    timestamp_ms: float
    buffer_set: str
    pid: int
    buffer_name: str
    is_oldest: bool = False
    severity: str = "INFO"
    tid: Optional[int] = None
    code: int = 0
    message: str = ""


class ThreadSegment(BaseModel):
    pid: int
    tid: int
    process_name: str
    thread_label: str
    cpu: int
    state: str
    start_us: float
    end_us: float
    duration_us: float
    priority: int = 10


class ThreadMetrics(BaseModel):
    key: str
    pid: int
    tid: int
    process_name: str
    thread_label: str
    base_priority: int = 10
    min_priority: int = 10
    max_priority: int = 10
    policy: str = "FIFO"
    activations: int = 0
    total_run_us: float = 0.0
    cpu_share_pct: float = 0.0
    wcet_us: float = 0.0
    avg_exec_us: float = 0.0
    p50_us: float = 0.0
    p95_us: float = 0.0
    p99_us: float = 0.0
    max_ready_wait_us: float = 0.0
    jitter_us: float = 0.0
    ipc_blocked_us: float = 0.0
    deadline_us: Optional[float] = None
    deadline_misses: int = 0
    preemptions: int = 0


class CoreUtilization(BaseModel):
    cpu: int
    busy_us: float = 0.0
    irq_us: float = 0.0
    idle_us: float = 0.0
    utilization_pct: float = 0.0
    irq_pct: float = 0.0
    context_switches: int = 0


class PriorityInversionIncident(BaseModel):
    id: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM"] = "CRITICAL"
    start_us: float
    end_us: float
    duration_us: float
    high_prio_client: str
    high_prio: int
    blocked_server: str
    server_prio: int
    preempting_thread: str
    preempting_prio: int
    rcvid: Optional[str] = None
    mechanism: str
    explanation: str
    remediation_c: str


class IrqStormIncident(BaseModel):
    id: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM"] = "HIGH"
    irq_vector: str
    cpu: int
    start_us: float
    end_us: float
    count: int
    rate_hz: float
    total_cpu_time_us: float
    cpu_share_pct: float
    impacted_threads: list[str] = Field(default_factory=list)
    explanation: str
    remediation: str


class DeadlineMissIncident(BaseModel):
    id: str
    thread_label: str
    pid: int
    tid: int
    frame_id: Optional[str] = None
    deadline_us: float
    actual_us: float
    overrun_us: float
    timestamp_us: float
    root_cause: str
    linked_incident_ids: list[str] = Field(default_factory=list)


class IpcNode(BaseModel):
    id: str
    pid: int
    name: str
    role: Literal["RESMGR", "CLIENT", "HYBRID", "KERNEL"] = "HYBRID"
    resource_paths: list[str] = Field(default_factory=list)
    priority_range: str = "10"
    thread_count: int = 1
    avg_cpu_pct: float = 0.0
    has_anomaly: bool = False
    anomaly_note: Optional[str] = None


class IpcEdge(BaseModel):
    source: str
    target: str
    kind: Literal["MSG_SYNC", "PULSE_ASYNC", "SIGNAL"] = "MSG_SYNC"
    count: int = 0
    avg_latency_us: float = 0.0
    max_latency_us: float = 0.0
    p99_latency_us: float = 0.0
    priority_inherited: bool = True
    has_inversion: bool = False
    rcvid_samples: list[str] = Field(default_factory=list)


class IpcTopology(BaseModel):
    nodes: list[IpcNode] = Field(default_factory=list)
    edges: list[IpcEdge] = Field(default_factory=list)
    total_messages: int = 0
    total_pulses: int = 0
    critical_path: list[str] = Field(default_factory=list)


class AuditFinding(BaseModel):
    id: str
    rule_id: str
    source: Literal["buildfile", "secpol", "cross-check"]
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    line: int = 1
    title: str
    description: str
    evidence: str = ""
    standard_ref: str = "QNX 8.0 Hardening Guide"
    remediation: str
    snippet_fix: Optional[str] = None


class BuildfileSummary(BaseModel):
    arch: Optional[str] = None
    boot_type: Optional[str] = None
    kernel_binary: Optional[str] = None
    instrumented: bool = False
    has_secpolpush: bool = False
    secpolpush_line: Optional[int] = None
    has_slogger2: bool = False
    services: list[dict[str, Any]] = Field(default_factory=list)
    libraries: list[str] = Field(default_factory=list)
    symlinks: list[dict[str, str]] = Field(default_factory=list)
    waitfor_paths: list[str] = Field(default_factory=list)


class SecpolSummary(BaseModel):
    types: list[str] = Field(default_factory=list)
    abilities_by_type: dict[str, list[str]] = Field(default_factory=dict)
    attach_rules: list[dict[str, str]] = Field(default_factory=list)
    channel_rules: list[dict[str, str]] = Field(default_factory=list)
    transition_pairs: list[dict[str, str]] = Field(default_factory=list)
    least_privilege_score: int = 100


class SecurityBootAuditResult(BaseModel):
    overall_score: int
    grade: Literal["A", "B", "C", "D", "F"]
    findings: list[AuditFinding] = Field(default_factory=list)
    buildfile_summary: Optional[BuildfileSummary] = None
    secpol_summary: Optional[SecpolSummary] = None
    hardened_secpol: str = ""
    hardened_diff: str = ""


class TraceAnalysisResult(BaseModel):
    scenario_id: str = "custom"
    scenario_name: str = "Custom QNX 8.0 Trace"
    description: str = ""
    header: TraceHeader
    duration_us: float = 0.0
    total_events: int = 0
    slog2_count: int = 0
    health_score: int = 100
    health_status: Literal["HEALTHY", "DEGRADED", "CRITICAL"] = "HEALTHY"
    cores: list[CoreUtilization] = Field(default_factory=list)
    threads: list[ThreadMetrics] = Field(default_factory=list)
    timeline_segments: list[ThreadSegment] = Field(default_factory=list)
    irq_events: list[dict[str, Any]] = Field(default_factory=list)
    priority_inversions: list[PriorityInversionIncident] = Field(default_factory=list)
    irq_storms: list[IrqStormIncident] = Field(default_factory=list)
    deadline_misses: list[DeadlineMissIncident] = Field(default_factory=list)
    ipc_topology: IpcTopology = Field(default_factory=IpcTopology)
    correlated_logs: list[Slog2Entry] = Field(default_factory=list)
    latency_histogram: list[dict[str, Any]] = Field(default_factory=list)


class CopilotDiagnosis(BaseModel):
    mode: Literal["deterministic", "llm"] = "deterministic"
    model: str = "qnx-pulse-rule-engine-v1"
    summary: str
    root_causes: list[dict[str, Any]] = Field(default_factory=list)
    action_plan: list[dict[str, Any]] = Field(default_factory=list)
    code_patches: list[dict[str, Any]] = Field(default_factory=list)
    safety_assessment: str = ""


class AnalyzeRequest(BaseModel):
    trace_text: str
    slog2_text: str = ""
    scenario_id: str = "custom"
    scenario_name: str = "Uploaded QNX 8.0 Trace"
    description: str = ""


class AuditRequest(BaseModel):
    buildfile_text: str = ""
    secpol_text: str = ""


class CopilotRequest(BaseModel):
    question: str = ""
    scenario_id: Optional[str] = None
    trace_text: Optional[str] = None
    slog2_text: Optional[str] = None
    buildfile_text: Optional[str] = None
    secpol_text: Optional[str] = None
    llm_provider: Optional[Literal["none", "openai", "anthropic", "ollama"]] = "none"
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None


class ComplianceReportRequest(BaseModel):
    scenario_id: Optional[str] = None
    trace_text: Optional[str] = None
    slog2_text: Optional[str] = None
    buildfile_text: Optional[str] = None
    secpol_text: Optional[str] = None
    standard: Literal["ISO-26262-ASIL-D", "IEC-62304-CLASS-C", "IEC-61508-SIL-3"] = "ISO-26262-ASIL-D"
    format: Literal["markdown", "json"] = "markdown"
