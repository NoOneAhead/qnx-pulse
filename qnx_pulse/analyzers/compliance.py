"""ISO 26262 / IEC 62304 / IEC 61508 Verification & Audit Report Exporter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from qnx_pulse.models import SecurityBootAuditResult, TraceAnalysisResult


def generate_compliance_report(
    trace_result: Optional[TraceAnalysisResult],
    audit_result: Optional[SecurityBootAuditResult],
    standard: str = "ISO-26262-ASIL-D",
    fmt: str = "markdown",
) -> str:
    """Generate a structured compliance verification report in Markdown or JSON."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rt_pass = bool(
        trace_result is None
        or (
            not trace_result.priority_inversions
            and not trace_result.irq_storms
            and not trace_result.deadline_misses
        )
    )
    sec_pass = bool(
        audit_result is None
        or not any(f.severity == "CRITICAL" for f in audit_result.findings)
    )
    overall_verdict = "PASS" if (rt_pass and sec_pass) else "FAIL — REMEDIATION REQUIRED"

    payload: dict[str, Any] = {
        "tool": "QNX-Pulse v1.0.0",
        "standard": standard,
        "generated_at_utc": generated_at,
        "overall_verdict": overall_verdict,
        "target_os": (
            f"{trace_result.header.sysname} {trace_result.header.sys_release} ({trace_result.header.machine})"
            if trace_result
            else "QNX 8.0.0"
        ),
        "real_time_verification": trace_result.model_dump() if trace_result else None,
        "security_boot_verification": audit_result.model_dump() if audit_result else None,
    }

    if fmt == "json":
        return json.dumps(payload, indent=2)

    lines: list[str] = [
        f"# QNX-Pulse Verification & Compliance Audit Report ({standard})",
        "",
        f"- **Generated (UTC):** `{generated_at}`",
        f"- **Target RTOS:** `{payload['target_os']}`",
        f"- **Overall Verdict:** **{overall_verdict}**",
        "",
        "---",
        "",
    ]

    if trace_result:
        lines.extend([
            "## 1. Real-Time Microkernel Trace Verification",
            "",
            f"- **Scenario:** {trace_result.scenario_name} (`{trace_result.scenario_id}`)",
            f"- **Trace File:** `{trace_result.header.file_name}` ({trace_result.total_events} events over {trace_result.duration_us/1000:.2f} ms on {trace_result.header.cpu_num} cores)",
            f"- **Health Score:** **{trace_result.health_score}/100** (`{trace_result.health_status}`)",
            f"- **Priority Inversions:** `{len(trace_result.priority_inversions)}` | **IRQ Storms:** `{len(trace_result.irq_storms)}` | **Deadline Misses:** `{len(trace_result.deadline_misses)}`",
            "",
            "### Per-Thread WCET & Determinism Table",
            "",
            "| Thread | Prio | Policy | Activations | WCET (us) | p99 (us) | Jitter (us) | IPC Blocked (us) | Deadline Misses |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|",
        ])
        for t in trace_result.threads:
            lines.append(
                f"| `{t.thread_label}` | {t.min_priority}-{t.max_priority} | {t.policy} | {t.activations} | "
                f"{t.wcet_us:.1f} | {t.p99_us:.1f} | {t.jitter_us:.1f} | {t.ipc_blocked_us:.1f} | {t.deadline_misses} |"
            )
        lines.append("")

        if trace_result.priority_inversions:
            lines.append("### Critical Priority Inversion Incidents")
            lines.append("")
            for pi in trace_result.priority_inversions:
                lines.append(f"- **{pi.id} [{pi.severity}]**: {pi.explanation}")
                lines.append(f"  - *Mechanism:* {pi.mechanism}")
            lines.append("")

        if trace_result.irq_storms:
            lines.append("### Interrupt Storm Incidents")
            lines.append("")
            for st in trace_result.irq_storms:
                lines.append(f"- **{st.id} [{st.severity}]**: {st.explanation}")
            lines.append("")

        if trace_result.deadline_misses:
            lines.append("### Deadline Miss Root Causes")
            lines.append("")
            for dm in trace_result.deadline_misses:
                lines.append(
                    f"- **{dm.id}** `{dm.thread_label}` (frame `{dm.frame_id}`): "
                    f"actual `{dm.actual_us/1000:.2f} ms` vs deadline `{dm.deadline_us/1000:.2f} ms` — {dm.root_cause}"
                )
            lines.append("")

    if audit_result:
        lines.extend([
            "## 2. QNX 8.0 IFS `.build` & `secpol` Security Audit",
            "",
            f"- **Security & Boot Score:** **{audit_result.overall_score}/100** (Grade **{audit_result.grade}**)",
            f"- **Findings Count:** `{len(audit_result.findings)}`",
            "",
        ])
        if audit_result.findings:
            lines.extend([
                "| Rule ID | Severity | Source | Line | Finding | Standard Reference |",
                "|---|---|---|---:|---|---|",
            ])
            for f in audit_result.findings:
                lines.append(
                    f"| `{f.rule_id}` | **{f.severity}** | `{f.source}` | {f.line} | {f.title} | {f.standard_ref} |"
                )
            lines.append("")
        else:
            lines.append("All QNX 8.0 boot sequencing and least-privilege `secpol` checks passed cleanly.\n")

        if audit_result.hardened_diff.strip():
            lines.extend([
                "### Recommended Auto-Hardened `secpol` Diff",
                "",
                "```diff",
                audit_result.hardened_diff.rstrip(),
                "```",
                "",
            ])

    lines.append("---")
    lines.append("*Generated by QNX-Pulse — QNX 8.0 Microkernel Trace, IPC Topology, Buildfile & Secpol Studio*")
    return "\n".join(lines) + "\n"
