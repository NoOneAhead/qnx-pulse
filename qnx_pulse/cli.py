"""QNX-Pulse CLI (`qnx-pulse`) — Real-Time Trace Analyzer, Buildfile/Secpol Auditor & Web Studio Launcher."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from qnx_pulse import __version__
from qnx_pulse.analyzers import (
    analyze_trace,
    audit_security_and_boot,
    diagnose_with_copilot,
    generate_compliance_report,
)
from qnx_pulse.datasets import list_scenarios, load_scenario

app = typer.Typer(
    name="qnx-pulse",
    help="QNX-Pulse: QNX 8.0 Microkernel Trace, IPC Topology, Buildfile & Secpol Studio",
    add_completion=False,
)
console = Console()


@app.command()
def scenarios() -> None:
    """List built-in QNX 8.0 real-time and security benchmark scenarios."""
    items = list_scenarios()
    table = Table(title="QNX-Pulse Built-In QNX 8.0 Scenarios")
    table.add_column("Scenario ID", style="cyan", no_wrap=True)
    table.add_column("Domain", style="magenta")
    table.add_column("Arch", style="green")
    table.add_column("Name")
    for s in items:
        table.add_row(s["id"], s.get("domain", ""), s.get("arch", ""), s["name"])
    console.print(table)


@app.command()
def analyze(
    trace_file: Optional[Path] = typer.Option(None, "--trace", "-t", help="Path to QNX 8.0 `traceprinter` output file"),
    slog2_file: Optional[Path] = typer.Option(None, "--slog2", "-s", help="Optional path to `slog2info` log file"),
    scenario: Optional[str] = typer.Option(None, "--scenario", help="Run against a built-in scenario ID"),
    json_out: bool = typer.Option(False, "--json", help="Emit structured JSON instead of rich tables"),
    fail_on_critical: bool = typer.Option(False, "--fail-on-critical", help="Exit with code 2 if CRITICAL incidents or deadline misses are detected (CI gate)"),
) -> None:
    """Analyze a QNX 8.0 microkernel trace for priority inversions, IRQ storms, WCET, and deadline misses."""
    if scenario:
        data = load_scenario(scenario)
        if not data:
            console.print(f"[red]Unknown scenario:[/red] {scenario}")
            raise typer.Exit(code=1)
        trace_text = data["trace_text"]
        slog2_text = data["slog2_text"]
        sname = data["meta"]["name"]
        sid = data["meta"]["id"]
    elif trace_file:
        if not trace_file.exists():
            console.print(f"[red]Trace file not found:[/red] {trace_file}")
            raise typer.Exit(code=1)
        trace_text = trace_file.read_text(encoding="utf-8")
        slog2_text = slog2_file.read_text(encoding="utf-8") if (slog2_file and slog2_file.exists()) else ""
        sname = trace_file.name
        sid = "cli"
    else:
        console.print("[yellow]Provide either --trace <file> or --scenario <id>.[/yellow]")
        raise typer.Exit(code=1)

    res = analyze_trace(trace_text, slog2_text, scenario_id=sid, scenario_name=sname)
    if json_out:
        typer.echo(json.dumps(res.model_dump(), indent=2))
    else:
        status_color = "green" if res.health_status == "HEALTHY" else ("yellow" if res.health_status == "DEGRADED" else "red")
        console.print(
            Panel.fit(
                f"[bold]{res.scenario_name}[/bold]\n"
                f"Target: [cyan]{res.header.sysname} {res.header.sys_release} ({res.header.machine}, {res.header.cpu_num} CPUs)[/cyan]\n"
                f"Events: {res.total_events} | Duration: {res.duration_us/1000:.2f} ms | "
                f"Health: [{status_color}]{res.health_score}/100 ({res.health_status})[/{status_color}]\n"
                f"Priority Inversions: [bold]{len(res.priority_inversions)}[/bold] | "
                f"IRQ Storms: [bold]{len(res.irq_storms)}[/bold] | "
                f"Deadline Misses: [bold]{len(res.deadline_misses)}[/bold]",
                title="QNX-Pulse Real-Time Trace Summary",
            )
        )

        tt = Table(title="Per-Thread Real-Time Metrics")
        tt.add_column("Thread", style="cyan")
        tt.add_column("Prio", justify="right")
        tt.add_column("WCET (us)", justify="right")
        tt.add_column("p99 (us)", justify="right")
        tt.add_column("Jitter (us)", justify="right")
        tt.add_column("IPC Blocked (us)", justify="right")
        tt.add_column("Misses", justify="right")
        for t in res.threads:
            miss_str = f"[red]{t.deadline_misses}[/red]" if t.deadline_misses else "0"
            tt.add_row(
                t.thread_label,
                f"{t.min_priority}-{t.max_priority}",
                f"{t.wcet_us:.1f}",
                f"{t.p99_us:.1f}",
                f"{t.jitter_us:.1f}",
                f"{t.ipc_blocked_us:.1f}",
                miss_str,
            )
        console.print(tt)

        for pi in res.priority_inversions:
            console.print(f"[red]\\[{escape(pi.id)} {escape(pi.severity)}][/red] {escape(pi.explanation)}")
        for st in res.irq_storms:
            console.print(f"[red]\\[{escape(st.id)} {escape(st.severity)}][/red] {escape(st.explanation)}")
        for dm in res.deadline_misses:
            console.print(f"[red]\\[{escape(dm.id)} DEADLINE MISS][/red] {escape(dm.thread_label)}: {dm.actual_us/1000:.2f}ms > {dm.deadline_us/1000:.2f}ms — {escape(dm.root_cause)}")

    if fail_on_critical and (res.priority_inversions or res.irq_storms or res.deadline_misses):
        raise typer.Exit(code=2)


@app.command()
def audit(
    buildfile: Optional[Path] = typer.Option(None, "--build", "-b", help="Path to QNX 8.0 mkifs `.build` file"),
    secpol: Optional[Path] = typer.Option(None, "--secpol", "-p", help="Path to QNX 8.0 `.secpol` policy file"),
    scenario: Optional[str] = typer.Option(None, "--scenario", help="Audit a built-in scenario ID"),
    write_hardened: Optional[Path] = typer.Option(None, "--write-hardened", help="Write auto-hardened `.secpol` policy to file"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output"),
    fail_on_critical: bool = typer.Option(False, "--fail-on-critical", help="Exit with code 2 on CRITICAL findings"),
) -> None:
    """Audit QNX 8.0 IFS `.build` and `secpol` files and generate least-privilege hardening diffs."""
    if scenario:
        data = load_scenario(scenario)
        if not data:
            console.print(f"[red]Unknown scenario:[/red] {scenario}")
            raise typer.Exit(code=1)
        bf_text = data["buildfile_text"]
        sp_text = data["secpol_text"]
    else:
        bf_text = buildfile.read_text(encoding="utf-8") if (buildfile and buildfile.exists()) else ""
        sp_text = secpol.read_text(encoding="utf-8") if (secpol and secpol.exists()) else ""
        if not bf_text and not sp_text:
            console.print("[yellow]Provide --build, --secpol, or --scenario.[/yellow]")
            raise typer.Exit(code=1)

    res = audit_security_and_boot(bf_text, sp_text)
    if write_hardened:
        write_hardened.write_text(res.hardened_secpol, encoding="utf-8")
        console.print(f"[green]Wrote hardened QNX 8.0 secpol to {write_hardened}[/green]")

    if json_out:
        typer.echo(json.dumps(res.model_dump(), indent=2))
    else:
        grade_color = "green" if res.grade in ("A", "B") else ("yellow" if res.grade == "C" else "red")
        console.print(
            Panel.fit(
                f"Security & Boot Score: [{grade_color}][bold]{res.overall_score}/100 (Grade {res.grade})[/bold][/{grade_color}] | "
                f"Findings: {len(res.findings)}",
                title="QNX-Pulse Static Security & Boot Audit",
            )
        )
        if res.findings:
            ft = Table(title="Audit Findings")
            ft.add_column("Rule", style="cyan", no_wrap=True)
            ft.add_column("Sev", no_wrap=True)
            ft.add_column("Src", no_wrap=True)
            ft.add_column("Line", justify="right")
            ft.add_column("Title")
            for f in res.findings:
                sev_style = "red" if f.severity == "CRITICAL" else ("yellow" if f.severity == "HIGH" else "blue")
                ft.add_row(escape(f.rule_id), f"[{sev_style}]{escape(f.severity)}[/{sev_style}]", escape(f.source), str(f.line), escape(f.title))
            console.print(ft)

    if fail_on_critical and any(f.severity == "CRITICAL" for f in res.findings):
        raise typer.Exit(code=2)


@app.command()
def report(
    scenario: str = typer.Option("adas_aeb_inversion", "--scenario", help="Scenario ID to export"),
    standard: str = typer.Option("ISO-26262-ASIL-D", "--standard", help="Compliance standard"),
    fmt: str = typer.Option("markdown", "--format", "-f", help="Output format: markdown or json"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Destination file path (defaults to stdout)"),
) -> None:
    """Export an ISO 26262 / IEC 62304 verification evidence report."""
    data = load_scenario(scenario)
    if not data:
        console.print(f"[red]Unknown scenario:[/red] {scenario}")
        raise typer.Exit(code=1)
    tr = analyze_trace(data["trace_text"], data["slog2_text"], scenario_id=data["meta"]["id"], scenario_name=data["meta"]["name"])
    au = audit_security_and_boot(data["buildfile_text"], data["secpol_text"])
    content = generate_compliance_report(tr, au, standard=standard, fmt=fmt)
    if out:
        out.write_text(content, encoding="utf-8")
        console.print(f"[green]Compliance report written to {out}[/green]")
    else:
        typer.echo(content)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8080, "--port", "-p", help="Bind port"),
) -> None:
    """Launch the QNX-Pulse Mission Control Web UI & REST API."""
    console.print(
        Panel.fit(
            f"[bold cyan]QNX-Pulse Studio v{__version__}[/bold cyan]\n"
            f"Mission Control UI: [link=http://{host}:{port}/]http://{host}:{port}/[/link]\n"
            f"QNX 8.0 Codelab:    [link=http://{host}:{port}/codelab/]http://{host}:{port}/codelab/[/link]\n"
            f"OpenAPI Docs:       [link=http://{host}:{port}/docs]http://{host}:{port}/docs[/link]",
            title="Starting QNX-Pulse Server",
        )
    )
    uvicorn.run("qnx_pulse.server:app", host=host, port=port, reload=False)


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())
