"""Tests for QNX 8.0 real-time trace, IPC topology, security/boot audit, copilot, and compliance analyzers."""

import json

from qnx_pulse.analyzers import (
    analyze_trace,
    audit_security_and_boot,
    diagnose_with_copilot,
    generate_compliance_report,
)
from qnx_pulse.datasets import load_scenario


def test_adas_aeb_detects_priority_inversion_and_deadline_miss():
    data = load_scenario("adas_aeb_inversion")
    assert data is not None
    res = analyze_trace(data["trace_text"], data["slog2_text"], "adas_aeb_inversion", data["meta"]["name"])

    assert res.health_status == "CRITICAL"
    assert res.health_score < 70
    assert len(res.priority_inversions) == 1
    pi = res.priority_inversions[0]
    assert pi.severity == "CRITICAL"
    assert pi.high_prio == 52
    assert pi.server_prio == 18
    assert pi.preempting_prio == 30
    assert "_NTO_CHF_FIXED_PRIORITY" in pi.mechanism
    assert pi.duration_us > 10_000.0

    assert len(res.deadline_misses) == 1
    dm = res.deadline_misses[0]
    assert dm.overrun_us > 2000.0
    assert pi.id in dm.linked_incident_ids

    # IPC topology flags the inverted channel
    assert any(e.has_inversion for e in res.ipc_topology.edges)
    assert any("/dev/lidar_fusion" in n.resource_paths for n in res.ipc_topology.nodes)


def test_surgical_robot_detects_irq_storm():
    data = load_scenario("surgical_robot_irq_storm")
    assert data is not None
    res = analyze_trace(data["trace_text"], data["slog2_text"], "surgical_robot_irq_storm", data["meta"]["name"])

    assert res.health_status == "CRITICAL"
    assert len(res.irq_storms) == 1
    st = res.irq_storms[0]
    assert st.cpu == 0
    assert st.count >= 15
    assert st.rate_hz > 5000.0
    assert len(res.deadline_misses) == 2
    assert all(st.id in dm.linked_incident_ids for dm in res.deadline_misses)


def test_amr_healthy_baseline_passes_all_invariants():
    data = load_scenario("amr_fleet_healthy_baseline")
    assert data is not None
    res = analyze_trace(data["trace_text"], data["slog2_text"], "amr_fleet_healthy_baseline", data["meta"]["name"])

    assert res.health_status == "HEALTHY"
    assert res.health_score == 100
    assert len(res.priority_inversions) == 0
    assert len(res.irq_storms) == 0
    assert len(res.deadline_misses) == 0

    # Verify lidar_fusion inherited priority 52 from motion_planner!
    lidar = next(t for t in res.threads if t.process_name == "lidar_fusion")
    assert lidar.min_priority == 18
    assert lidar.max_priority == 52

    # Security & boot audit must score Grade A (100/100)
    au = audit_security_and_boot(data["buildfile_text"], data["secpol_text"])
    assert au.grade == "A"
    assert au.overall_score == 100
    assert len(au.findings) == 0


def test_security_boot_auditor_and_auto_hardener():
    data = load_scenario("adas_aeb_inversion")
    assert data is not None
    au = audit_security_and_boot(data["buildfile_text"], data["secpol_text"])
    rule_ids = {f.rule_id for f in au.findings}

    assert "QNX8-BUILD-002" in rule_ids  # deprecated QNX 7 -mL superlock flag
    assert "QNX8-BUILD-004" in rule_ids  # late secpolpush
    assert "QNX8-SECPOL-002" in rule_ids  # unbounded mem_phys
    assert "QNX8-SECPOL-003" in rule_ids  # unbounded setuid
    assert "QNX8-SECPOL-004" in rule_ids  # wildcard allow_attach /dev/...
    assert "QNX8-SECPOL-006" in rule_ids  # missing _run_t type
    assert "QNX8-XCHK-001" in rule_ids   # brake_act_t missing in secpol
    assert au.grade in ("D", "F")
    assert "lidar_fusion_run_t" in au.hardened_secpol
    assert "brake_act_t" in au.hardened_secpol
    assert "--- original.secpol" in au.hardened_diff

    # Re-auditing ONLY the auto-hardened secpol must achieve 100/100 Grade A!
    re_audit = audit_security_and_boot("", au.hardened_secpol)
    assert re_audit.grade == "A"
    assert re_audit.overall_score == 100


def test_copilot_and_compliance_report_exporters():
    data = load_scenario("adas_aeb_inversion")
    tr = analyze_trace(data["trace_text"], data["slog2_text"], "adas_aeb_inversion", data["meta"]["name"])
    au = audit_security_and_boot(data["buildfile_text"], data["secpol_text"])

    diag = diagnose_with_copilot(question="Why did AEB miss its deadline?", trace_result=tr, audit_result=au)
    assert diag.mode == "deterministic"
    assert len(diag.root_causes) >= 2
    assert len(diag.code_patches) >= 1
    assert "NON-COMPLIANT" in diag.safety_assessment

    md = generate_compliance_report(tr, au, standard="ISO-26262-ASIL-D", fmt="markdown")
    assert "# QNX-Pulse Verification & Compliance Audit Report (ISO-26262-ASIL-D)" in md
    assert "FAIL" in md
    assert "PI-001" in md

    js = generate_compliance_report(tr, au, standard="IEC-62304-CLASS-C", fmt="json")
    parsed = json.loads(js)
    assert parsed["standard"] == "IEC-62304-CLASS-C"
    assert parsed["real_time_verification"]["health_status"] == "CRITICAL"
