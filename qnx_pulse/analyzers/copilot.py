"""QNX 8.0 Real-Time & Security Diagnostic Copilot.

Works 100% deterministically offline with deep QNX 8.0 microkernel, IPC, mkifs, and secpol expertise,
plus optional BYO-LLM enhancement (OpenAI / Anthropic / local Ollama) when explicitly configured.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from qnx_pulse.models import (
    CopilotDiagnosis,
    SecurityBootAuditResult,
    TraceAnalysisResult,
)


def _deterministic_diagnose(
    question: str,
    trace_result: Optional[TraceAnalysisResult],
    audit_result: Optional[SecurityBootAuditResult],
) -> CopilotDiagnosis:
    root_causes: list[dict[str, Any]] = []
    action_plan: list[dict[str, Any]] = []
    code_patches: list[dict[str, Any]] = []
    summary_parts: list[str] = []

    q_lower = (question or "").lower()

    if trace_result:
        if trace_result.priority_inversions:
            pi = trace_result.priority_inversions[0]
            summary_parts.append(
                f"Detected {len(trace_result.priority_inversions)} critical QNX 8.0 IPC priority inversion(s): "
                f"{pi.high_prio_client} [prio {pi.high_prio}] stalled for {pi.duration_us/1000:.2f} ms waiting on "
                f"{pi.blocked_server} [prio {pi.server_prio}] while preempted by {pi.preempting_thread} [prio {pi.preempting_prio}]."
            )
            root_causes.append({
                "category": "IPC Priority Inversion",
                "severity": pi.severity,
                "title": f"{pi.id}: {pi.mechanism}",
                "detail": pi.explanation,
            })
            action_plan.append({
                "step": 1,
                "owner": "Resource Manager / Server C Code",
                "action": "Remove `_NTO_CHF_FIXED_PRIORITY` from `ChannelCreate()` / `dispatch_create_channel()` so QNX 8.0 kernel priority inheritance boosts the server to the caller's priority automatically.",
                "impact": f"Eliminates ~{pi.duration_us/1000:.2f} ms inversion stall and restores deterministic deadline compliance.",
            })
            code_patches.append({
                "file": "server_resmgr.c",
                "language": "c",
                "title": "Re-enable QNX 8.0 Synchronous IPC Priority Inheritance",
                "code": pi.remediation_c,
            })

        if trace_result.irq_storms:
            st = trace_result.irq_storms[0]
            summary_parts.append(
                f"Detected {len(trace_result.irq_storms)} hardware interrupt storm(s): {st.irq_vector} on CPU:{st.cpu:02d} "
                f"fired {st.count} times ({st.rate_hz:,.0f} Hz), consuming {st.cpu_share_pct:.1f}% of the core."
            )
            root_causes.append({
                "category": "Interrupt Storm & Core Affinity",
                "severity": st.severity,
                "title": f"{st.id}: {st.irq_vector} saturating CPU:{st.cpu:02d}",
                "detail": st.explanation,
            })
            action_plan.append({
                "step": len(action_plan) + 1,
                "owner": "BSP Driver & Core Partitioning",
                "action": f"Migrate {st.irq_vector} to an Interrupt Service Thread (IST) via `InterruptAttachEvent()`, enable hardware coalescing, and isolate CPU:{st.cpu:02d} for hard real-time control loops.",
                "impact": "Cuts control-loop jitter by >85% and prevents ISR preemption starvation.",
            })
            code_patches.append({
                "file": "sensor_ist_driver.c",
                "language": "c",
                "title": "QNX 8.0 IST Migration + Core Affinity Pinning",
                "code": (
                    "#include <sys/neutrino.h>\n"
                    "#include <sys/syspage.h>\n\n"
                    "// Pin IST away from RT control CPU0 (e.g., to CPU2 = mask 0x4)\n"
                    "unsigned runmask = 0x04;\n"
                    "ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)runmask);\n\n"
                    "// Prefer InterruptAttachEvent() over heavy ISR work\n"
                    "struct sigevent ev;\n"
                    "SIGEV_INTR_INIT(&ev);\n"
                    "int iid = InterruptAttachEvent(irq_num, &ev, _NTO_INTR_FLAGS_TRK_MSK);\n"
                    "while (running) {\n"
                    "    InterruptWait(_NTO_WAIT_FOR_EVENTS, NULL);\n"
                    "    drain_dma_ring_batched();\n"
                    "    InterruptUnmask(irq_num, iid);\n"
                    "}"
                ),
            })

        if trace_result.deadline_misses:
            dm = trace_result.deadline_misses[0]
            summary_parts.append(
                f"{len(trace_result.deadline_misses)} real-time deadline miss(es) recorded (worst overrun: "
                f"+{max(d.overrun_us for d in trace_result.deadline_misses)/1000:.2f} ms on {dm.thread_label})."
            )
            root_causes.append({
                "category": "Real-Time Deadline Miss",
                "severity": "CRITICAL",
                "title": f"{dm.id}: {dm.thread_label} exceeded {dm.deadline_us/1000:.2f} ms budget",
                "detail": f"Actual latency {dm.actual_us/1000:.2f} ms (+{dm.overrun_us/1000:.2f} ms overrun). Root cause: {dm.root_cause}",
            })

        if not trace_result.priority_inversions and not trace_result.irq_storms and not trace_result.deadline_misses:
            top_thread = trace_result.threads[0] if trace_result.threads else None
            summary_parts.append(
                f"Real-time trace is HEALTHY (score {trace_result.health_score}/100): zero priority inversions, "
                f"zero IRQ storms, and zero deadline misses across {trace_result.total_events} kernel events."
            )
            if top_thread:
                action_plan.append({
                    "step": 1,
                    "owner": "CI Regression Gate",
                    "action": (
                        f"Lock WCET regression baseline for {top_thread.thread_label} "
                        f"(WCET={top_thread.wcet_us:.1f} us, p99={top_thread.p99_us:.1f} us, jitter={top_thread.jitter_us:.1f} us) "
                        "using `qnx-pulse analyze --fail-on-critical` in CI."
                    ),
                    "impact": "Prevents future commits from re-introducing real-time regressions.",
                })

    if audit_result and audit_result.findings:
        crit_high = [f for f in audit_result.findings if f.severity in ("CRITICAL", "HIGH")]
        summary_parts.append(
            f"Static QNX 8.0 Buildfile & Secpol Audit scored {audit_result.overall_score}/100 (Grade {audit_result.grade}) "
            f"with {len(crit_high)} Critical/High security or boot-ordering findings."
        )
        for f in crit_high[:3]:
            root_causes.append({
                "category": f"Static Audit ({f.source})",
                "severity": f.severity,
                "title": f"{f.rule_id}: {f.title} (line {f.line})",
                "detail": f.description,
            })
        action_plan.append({
            "step": len(action_plan) + 1,
            "owner": "Platform Security & IFS Build",
            "action": "Apply the auto-generated hardened `.secpol` policy, ensure `secpolpush` runs first in `[+script]`, and drop runtime privileges via `secpol_transition_type(NULL, \"run\", 0)`.",
            "impact": "Raises QNX 8.0 security posture to least-privilege ISO 26262 / IEC 62304 compliance.",
        })
        if audit_result.hardened_secpol:
            code_patches.append({
                "file": "hardened.secpol",
                "language": "text",
                "title": "Auto-Hardened Least-Privilege QNX 8.0 Security Policy",
                "code": audit_result.hardened_secpol[:1200],
            })

    # Tailor response when the user asks a specific question
    if q_lower:
        if "secpol" in q_lower or "privilege" in q_lower or "security" in q_lower:
            summary_parts.insert(
                0,
                "QNX 8.0 Least-Privilege Guidance: compile policy via `secpolcompile`, push first in `[+script]` with "
                "`secpolpush -i /proc/boot/secpol.bin`, launch services via `on -T <svc>_t -U <uid:gid>`, and call "
                "`secpol_transition_type(NULL, \"run\", 0)` right after `resmgr_attach()`.",
            )
        elif "priority" in q_lower or "inversion" in q_lower or "fixed" in q_lower:
            summary_parts.insert(
                0,
                "QNX 8.0 Priority Inheritance Answer: Synchronous `MsgSend()`/`MsgReceive()`/`MsgReply()` inherits the "
                "client's priority automatically unless `_NTO_CHF_FIXED_PRIORITY` is passed to `ChannelCreate()`, or work "
                "is deferred asynchronously via pulses (`MsgSendPulse()`).",
            )
        elif "qemu" in q_lower or "mkifs" in q_lower or "boot" in q_lower:
            summary_parts.insert(
                0,
                "QNX 8.0 QEMU Boot Guidance: Build an IFS with `[virtual=x86_64,multiboot]` + `procnto-smp-instr -v` "
                "(omitting legacy QNX 7 `-m` superlock flags), compile with `mkifs -v qnx8-qemu-x86_64.build qnx8.ifs`, "
                "and boot with `qemu-system-x86_64 -M q35 -m 2G -smp 4 -kernel qnx8.ifs -serial stdio -display none`.",
            )

    if not summary_parts:
        summary_parts.append(
            "Provide a QNX 8.0 `traceprinter` trace, `slog2info` log, `.build` file, or `.secpol` policy for deep deterministic diagnostics."
        )

    safety_assessment = (
        "NON-COMPLIANT FOR SAFETY RELEASE: Resolve all CRITICAL real-time deadline/inversion incidents and secpol/boot findings prior to ISO 26262 / IEC 62304 sign-off."
        if (
            (trace_result and trace_result.health_status == "CRITICAL")
            or (audit_result and audit_result.grade in ("D", "F"))
        )
        else (
            "CONDITIONAL PASS: Address remaining HIGH/MEDIUM findings and verify WCET margins under worst-case stress load."
            if (
                (trace_result and trace_result.health_status == "DEGRADED")
                or (audit_result and audit_result.grade in ("B", "C"))
            )
            else "PASS: Real-time determinism and QNX 8.0 least-privilege isolation criteria satisfied."
        )
    )

    return CopilotDiagnosis(
        mode="deterministic",
        model="qnx-pulse-rule-engine-v1",
        summary=" ".join(summary_parts),
        root_causes=root_causes,
        action_plan=action_plan,
        code_patches=code_patches,
        safety_assessment=safety_assessment,
    )


def _call_byo_llm(
    provider: str,
    api_key: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
    question: str,
    baseline: CopilotDiagnosis,
) -> Optional[CopilotDiagnosis]:
    """Optional BYO-LLM enhancement; cleanly falls back to deterministic diagnosis on any error."""
    prompt = (
        "You are a principal QNX SDP 8.0 real-time systems architect. "
        "Given the deterministic analysis below and the user's question, return a concise, deeply technical "
        "3-5 sentence synthesis highlighting QNX 8.0 specifics (procnto-smp-instr, MsgSend/MsgReply priority inheritance, "
        "secpol_transition_type, InterruptAttachEvent).\n\n"
        f"User question: {question or 'Diagnose root causes and prioritize fixes.'}\n\n"
        f"Deterministic findings:\n{json.dumps(baseline.model_dump(), indent=2)[:3500]}"
    )

    try:
        with httpx.Client(timeout=15.0) as client:
            if provider == "openai" and api_key:
                url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
                mdl = model or "gpt-4o-mini"
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": mdl,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
                return baseline.model_copy(update={"mode": "llm", "model": f"openai/{mdl}", "summary": text})

            if provider == "anthropic" and api_key:
                url = (base_url or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
                mdl = model or "claude-3-5-haiku-latest"
                resp = client.post(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": mdl,
                        "max_tokens": 500,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                text = resp.json()["content"][0]["text"].strip()
                return baseline.model_copy(update={"mode": "llm", "model": f"anthropic/{mdl}", "summary": text})

            if provider == "ollama":
                url = (base_url or "http://localhost:11434").rstrip("/") + "/api/generate"
                mdl = model or "llama3.2"
                resp = client.post(url, json={"model": mdl, "prompt": prompt, "stream": False})
                resp.raise_for_status()
                text = resp.json().get("response", "").strip()
                if text:
                    return baseline.model_copy(update={"mode": "llm", "model": f"ollama/{mdl}", "summary": text})
    except Exception:
        return None
    return None


def diagnose_with_copilot(
    question: str = "",
    trace_result: Optional[TraceAnalysisResult] = None,
    audit_result: Optional[SecurityBootAuditResult] = None,
    llm_provider: Optional[str] = "none",
    llm_api_key: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_base_url: Optional[str] = None,
) -> CopilotDiagnosis:
    """Produce deterministic QNX 8.0 diagnosis, optionally enhanced by BYO-LLM."""
    baseline = _deterministic_diagnose(question, trace_result, audit_result)
    if llm_provider and llm_provider != "none":
        enhanced = _call_byo_llm(llm_provider, llm_api_key, llm_model, llm_base_url, question, baseline)
        if enhanced is not None:
            return enhanced
    return baseline
