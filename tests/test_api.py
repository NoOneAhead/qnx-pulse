"""FastAPI integration tests for QNX-Pulse REST API & Web UI endpoints."""

from fastapi.testclient import TestClient

from qnx_pulse.server import app

client = TestClient(app)


def test_health_and_scenarios_endpoints():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["target_rtos"] == "QNX SDP 8.0"
    assert body["scenarios_available"] >= 3

    r2 = client.get("/api/scenarios")
    assert r2.status_code == 200
    ids = [s["id"] for s in r2.json()["scenarios"]]
    assert "adas_aeb_inversion" in ids
    assert "surgical_robot_irq_storm" in ids
    assert "amr_fleet_healthy_baseline" in ids


def test_get_scenario_full_payload():
    r = client.get("/api/scenarios/adas_aeb_inversion")
    assert r.status_code == 200
    data = r.json()
    assert data["trace_analysis"]["health_status"] == "CRITICAL"
    assert len(data["trace_analysis"]["priority_inversions"]) == 1
    assert data["audit_result"]["grade"] in ("D", "F")
    assert data["copilot"]["mode"] == "deterministic"

    r_404 = client.get("/api/scenarios/nonexistent")
    assert r_404.status_code == 404


def test_post_analyze_audit_copilot_and_reports():
    trace_sample = """
TRACE_SYSNAME:: QNX
TRACE_SYS_RELEASE:: 8.0.0
TRACE_CYCLES_PER_SEC:: 2500000000
TRACE_CPU_NUM:: 2
t:0x01000000 CPU:00 PROCESS : PROCCREATE_NAME ppid:1 pid:700 name:/proc/boot/ctrl
t:0x01000000 CPU:00 THREAD  : THRUNNING pid:700 tid:1 priority:40 policy:FIFO
t:0x0103d090 CPU:00 THREAD  : THNANOSLEEP pid:700 tid:1 priority:40
"""
    r_tr = client.post("/api/analyze/trace", json={"trace_text": trace_sample})
    assert r_tr.status_code == 200
    assert r_tr.json()["health_status"] == "HEALTHY"

    r_au = client.post(
        "/api/audit/security-boot",
        json={"secpol_text": "type app_t;\nallow app_t self:ability { root setuid };\nallow_attach app_t /dev/...;"},
    )
    assert r_au.status_code == 200
    assert r_au.json()["grade"] in ("D", "F")
    assert len(r_au.json()["findings"]) >= 3

    r_cp = client.post(
        "/api/copilot/diagnose",
        json={"scenario_id": "surgical_robot_irq_storm", "question": "How do I fix the IRQ storm?"},
    )
    assert r_cp.status_code == 200
    assert "InterruptAttachEvent" in str(r_cp.json())

    r_rep = client.post(
        "/api/reports/compliance",
        json={"scenario_id": "amr_fleet_healthy_baseline", "standard": "ISO-26262-ASIL-D", "format": "markdown"},
    )
    assert r_rep.status_code == 200
    assert "PASS" in r_rep.text


def test_web_ui_serves_html_and_assets():
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "QNX-PULSE" in r_root.text

    r_css = client.get("/static/styles.css")
    assert r_css.status_code == 200
    r_js = client.get("/static/app.js")
    assert r_js.status_code == 200


def test_codelab_and_target_artifacts_integrated():
    r_lab = client.get("/codelab/")
    assert r_lab.status_code == 200
    assert "Zero-Jitter QNX 8.0" in r_lab.text

    r_lab_js = client.get("/codelab/codelab.js")
    assert r_lab_js.status_code == 200

    # Verify our shipped target secpol and codelab secpol score Grade A in the auditor
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    target_secpol = (root / "target" / "qnx_pulse_agent" / "qnxpulse.secpol").read_text(encoding="utf-8")
    r_aud = client.post("/api/audit/security-boot", json={"secpol_text": target_secpol})
    assert r_aud.status_code == 200
    assert r_aud.json()["grade"] == "A"
    assert r_aud.json()["overall_score"] == 100

    lab_secpol = (root / "codelab" / "lab_files" / "lab.secpol").read_text(encoding="utf-8")
    r_lab_aud = client.post("/api/audit/security-boot", json={"secpol_text": lab_secpol})
    assert r_lab_aud.status_code == 200
    lab_body = r_lab_aud.json()
    # Verify syntax is valid and the lidar_mgr_t -> lidar_mgr_run_t privilege drop has zero findings
    assert "lidar_mgr_t" in lab_body["secpol_summary"]["types"]
    assert "lidar_mgr_run_t" in lab_body["secpol_summary"]["types"]
    assert not any("lidar_mgr" in f["title"] for f in lab_body["findings"])

