"""End-to-end CLI tests for `qnx-pulse` Typer commands."""

import json
from typer.testing import CliRunner

from qnx_pulse.cli import app

runner = CliRunner()


def test_cli_scenarios_and_analyze():
    res = runner.invoke(app, ["scenarios"])
    assert res.exit_code == 0
    assert "adas_aeb_inversion" in res.stdout

    res_json = runner.invoke(app, ["analyze", "--scenario", "adas_aeb_inversion", "--json"])
    assert res_json.exit_code == 0
    payload = json.loads(res_json.stdout)
    assert len(payload["priority_inversions"]) == 1

    # CI gate exits with code 2 on critical scenario, 0 on healthy baseline
    res_fail = runner.invoke(app, ["analyze", "--scenario", "adas_aeb_inversion", "--fail-on-critical"])
    assert res_fail.exit_code == 2

    res_pass = runner.invoke(app, ["analyze", "--scenario", "amr_fleet_healthy_baseline", "--fail-on-critical"])
    assert res_pass.exit_code == 0


def test_cli_audit_and_write_hardened(tmp_path):
    out_file = tmp_path / "hardened.secpol"
    res = runner.invoke(
        app,
        ["audit", "--scenario", "adas_aeb_inversion", "--write-hardened", str(out_file), "--fail-on-critical"],
    )
    assert res.exit_code == 2
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "lidar_fusion_run_t" in content

    # Verify hardened output passes cleanly
    res2 = runner.invoke(app, ["audit", "--secpol", str(out_file), "--fail-on-critical"])
    assert res2.exit_code == 0


def test_cli_report_export(tmp_path):
    out_md = tmp_path / "audit.md"
    res = runner.invoke(
        app,
        ["report", "--scenario", "surgical_robot_irq_storm", "--standard", "IEC-62304-CLASS-C", "--out", str(out_md)],
    )
    assert res.exit_code == 0
    assert out_md.exists()
    assert "IEC-62304-CLASS-C" in out_md.read_text(encoding="utf-8")
