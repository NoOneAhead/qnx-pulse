"""QNX 8.0 Static IFS `.build` & `secpol` Security/Boot Auditor + Auto-Hardener."""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Optional

from qnx_pulse.models import (
    AuditFinding,
    BuildfileSummary,
    SecpolSummary,
    SecurityBootAuditResult,
)
from qnx_pulse.parsers.buildfile import ParsedBuildfile, parse_buildfile
from qnx_pulse.parsers.secpol import ParsedSecpol, parse_secpol

VALID_SECPOL_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DANGEROUS_RUNTIME_ABILITIES = {
    "able_create",
    "xprocess_able",
    "root",
    "pathspace",
    "public_channel",
    "setuid",
    "setgid",
    "chroot",
    "rlimit",
}

SEVERITY_PENALTY = {
    "CRITICAL": 20,
    "HIGH": 11,
    "MEDIUM": 5,
    "LOW": 2,
    "INFO": 0,
}


def _compute_grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def _audit_buildfile(pb: ParsedBuildfile, findings: list[AuditFinding]) -> BuildfileSummary:
    fid = [0]

    def add(
        rule_id: str,
        severity: str,
        line: int,
        title: str,
        description: str,
        evidence: str,
        remediation: str,
        standard_ref: str = "QNX SDP 8.0 System Architecture & Hardening Guide",
        snippet_fix: Optional[str] = None,
    ) -> None:
        fid[0] += 1
        findings.append(
            AuditFinding(
                id=f"BF-{fid[0]:03d}",
                rule_id=rule_id,
                source="buildfile",
                severity=severity,  # type: ignore[arg-type]
                line=line,
                title=title,
                description=description,
                evidence=evidence,
                standard_ref=standard_ref,
                remediation=remediation,
                snippet_fix=snippet_fix,
            )
        )

    instrumented = bool(pb.kernel_binary and "instr" in pb.kernel_binary)

    # QNX8-BUILD-001: Instrumented kernel check
    if pb.kernel_binary and not instrumented:
        add(
            rule_id="QNX8-BUILD-001",
            severity="HIGH",
            line=pb.kernel_line or 1,
            title="Non-instrumented microkernel binary disables tracelogger",
            description=(
                f"IFS boots `{pb.kernel_binary}` instead of `procnto-smp-instr`. In QNX 8.0, "
                "kernel event tracing (`tracelogger` / `TraceEvent()`) requires the instrumented kernel."
            ),
            evidence=f"{pb.kernel_binary} {' '.join(pb.kernel_flags)}".strip(),
            remediation="Use `procnto-smp-instr -v` for diagnostic/verification builds (and QNX 8.0 hypervisor/VMX targets).",
            standard_ref="QNX SDP 8.0 System Analysis Toolkit (SAT)",
            snippet_fix="procnto-smp-instr -v",
        )

    # QNX8-BUILD-002: Deprecated QNX 7 superlocking flags
    if pb.kernel_binary and any(f.startswith("-m") and ("L" in f or "l" in f) for f in pb.kernel_flags):
        bad_flags = [f for f in pb.kernel_flags if f.startswith("-m")]
        add(
            rule_id="QNX8-BUILD-002",
            severity="MEDIUM",
            line=pb.kernel_line or 1,
            title="Deprecated QNX 7 memory superlocking flag on QNX 8.0 procnto",
            description=(
                "QNX SDP 8.0 enables memory superlocking by default. Legacy QNX 7.x `-mL`/`-ml` "
                "flags on `procnto-smp-instr` are obsolete and indicate an unmigrated buildfile."
            ),
            evidence=f"{pb.kernel_binary} {' '.join(bad_flags)}",
            remediation="Remove legacy `-mL`/`-ml` flags from `procnto-smp-instr` when migrating to QNX 8.0.",
            standard_ref="QNX SDP 8.0 Migration Guide (procnto-smp-instr)",
            snippet_fix="procnto-smp-instr -v",
        )

    # QNX8-BUILD-003 & 004: secpolpush presence and ordering
    if pb.secpolpush_line is None:
        add(
            rule_id="QNX8-BUILD-003",
            severity="CRITICAL",
            line=pb.kernel_line or 1,
            title="Missing mandatory `secpolpush` in startup script",
            description=(
                "The `[+script]` startup block does not invoke `secpolpush`. Without pushing a compiled "
                "security policy early at boot, QNX 8.0 type enforcement and pathspace restrictions are inactive."
            ),
            evidence="No `secpolpush` command found in `[+script]`.",
            remediation="Compile your policy with `secpolcompile -o secpol.bin policy.secpol` and run `secpolpush -i /proc/boot/secpol.bin` as the first action in `[+script]`.",
            standard_ref="ISO 26262-6 / QNX 8.0 Security Policy Enforcement",
            snippet_fix="secpolpush -i /proc/boot/secpol.bin",
        )
    else:
        early_svcs = [s for s in pb.services if s["line"] < pb.secpolpush_line]
        if early_svcs:
            names = ", ".join(s["name"] for s in early_svcs)
            add(
                rule_id="QNX8-BUILD-004",
                severity="CRITICAL",
                line=pb.secpolpush_line,
                title="Services launched BEFORE `secpolpush` enforces security policy",
                description=(
                    f"Services ({names}) start before `secpolpush` (line {pb.secpolpush_line}). "
                    "Processes started prior to policy push bypass secpol type containment and inherit unconfined root privileges."
                ),
                evidence=f"Service `{early_svcs[0]['name']}` on line {early_svcs[0]['line']} precedes `secpolpush` on line {pb.secpolpush_line}.",
                remediation="Move `secpolpush -i /proc/boot/secpol.bin` to the very top of `[+script]`, before launching `slogger2` or any resource managers.",
                standard_ref="QNX 8.0 Security Hardening — Early Policy Activation",
                snippet_fix="[+script] startup-script = {\n    secpolpush -i /proc/boot/secpol.bin\n    ...",
            )

        # QNX8-BUILD-008: Verify secpol.bin included in IFS files
        file_targets = [f["target"] for f in pb.files]
        if not any("secpol" in t and ".bin" in t for t in file_targets):
            add(
                rule_id="QNX8-BUILD-008",
                severity="HIGH",
                line=pb.secpolpush_line,
                title="`secpolpush` references policy binary not packaged in IFS",
                description=(
                    f"`secpolpush` expects `{pb.secpolpush_path or '/proc/boot/secpol.bin'}`, "
                    "but no `.bin` security policy file is listed in the IFS file manifest."
                ),
                evidence=f"secpolpush -i {pb.secpolpush_path or '/proc/boot/secpol.bin'}",
                remediation="Include `secpol.bin={./secpol.bin}` inside the IFS `[uid=0 gid=0]` files section.",
                snippet_fix="secpol.bin={./secpol.bin}",
            )

    # QNX8-BUILD-005: Unconfined root services
    for svc in pb.services:
        if svc["name"] in ("ksh", "sh", "slogger2", "pipe"):
            continue
        is_root = svc["uid_gid"] in (None, "0", "0:0")
        no_type = not svc["secpol_type"]
        if is_root or no_type:
            add(
                rule_id="QNX8-BUILD-005",
                severity="HIGH",
                line=svc["line"],
                title=f"Service `{svc['name']}` launched without least-privilege UID/secpol type",
                description=(
                    f"`{svc['name']}` is started without `on -T <type> -U <uid:gid>`. Running resource managers "
                    "or application services as unconfined root (UID 0) violates QNX 8.0 least-privilege isolation."
                ),
                evidence=svc["cmd"],
                remediation=f"Launch with `on -T {svc['name']}_t -U 120:120 /proc/boot/{svc['name']} &` and transition to `{svc['name']}_run_t` after init.",
                standard_ref="ISO 26262-6 / IEC 62304 Least Privilege",
                snippet_fix=f"on -T {svc['name']}_t -U 120:120 /proc/boot/{svc['name']} &",
            )

    # QNX8-BUILD-006: Missing slogger2
    if not pb.has_slogger2:
        add(
            rule_id="QNX8-BUILD-006",
            severity="MEDIUM",
            line=pb.kernel_line or 1,
            title="System logger `slogger2` missing from IFS startup script",
            description=(
                "Without `slogger2` running, `slog2f()` diagnostics from QNX 8.0 drivers, resource managers, "
                "and safety watchdogs are silently discarded."
            ),
            evidence="No `slogger2` launch in `[+script]`.",
            remediation="Start `on -T slogger2_t -U 21:21 /proc/boot/slogger2 &` followed by `waitfor /dev/slog2` early in `[+script]`.",
            snippet_fix="on -T slogger2_t -U 21:21 /proc/boot/slogger2 &\nwaitfor /dev/slog2 4",
        )

    # QNX8-BUILD-007: Missing waitfor synchronization for /dev/slog2 or resource managers
    wait_paths = [w["path"] for w in pb.waitfor_paths]
    if pb.has_slogger2 and not any("slog" in p for p in wait_paths) and len(pb.services) > 1:
        add(
            rule_id="QNX8-BUILD-007",
            severity="HIGH",
            line=pb.slogger2_line or 1,
            title="Boot race condition: missing `waitfor /dev/slog2` after `slogger2`",
            description=(
                "Dependent services start immediately after backgrounding `slogger2` without `waitfor /dev/slog2`. "
                "Early `slog2_register()` calls can fail intermittently with ENOENT during fast SMP boot."
            ),
            evidence="slogger2 started in background without `waitfor /dev/slog2`.",
            remediation="Add `waitfor /dev/slog2 4` immediately after launching `slogger2`.",
            standard_ref="QNX 8.0 Deterministic Boot Sequencing",
            snippet_fix="waitfor /dev/slog2 4",
        )

    # QNX8-BUILD-009: Missing LD_LIBRARY_PATH or core shared libs
    if "LD_LIBRARY_PATH" not in pb.env_vars:
        add(
            rule_id="QNX8-BUILD-009",
            severity="MEDIUM",
            line=pb.kernel_line or 1,
            title="Missing `LD_LIBRARY_PATH` in `[virtual=...]` boot environment",
            description="Dynamic executables in `/proc/boot` may fail to resolve shared libraries (`libc.so`, `libslog2.so`, `libsecpol.so`) if `LD_LIBRARY_PATH` is unset.",
            evidence="Environment variables: " + (", ".join(pb.env_vars.keys()) or "none"),
            remediation="Set `LD_LIBRARY_PATH=/proc/boot:/system/lib:/system/lib/dll` inside the `[virtual=...]` boot block.",
            snippet_fix="LD_LIBRARY_PATH=/proc/boot:/system/lib:/system/lib/dll",
        )

    if pb.has_slogger2 and not any("libslog2" in lib for lib in pb.libraries):
        add(
            rule_id="QNX8-BUILD-010",
            severity="MEDIUM",
            line=pb.slogger2_line or 1,
            title="`libslog2.so` not explicitly staged in IFS file manifest",
            description="`slogger2` clients dynamically link `libslog2.so`; omitting it from the IFS causes runtime loader failures in minimal QEMU images.",
            evidence=f"Staged libraries: {', '.join(pb.libraries) or 'none'}",
            remediation="Add `libslog2.so` (and `libsecpol.so` when using `secpol_transition_type()`) to the IFS file list.",
            snippet_fix="libc.so\nlibslog2.so\nlibsecpol.so",
        )

    return BuildfileSummary(
        arch=pb.arch,
        boot_type=pb.boot_type,
        kernel_binary=pb.kernel_binary,
        instrumented=instrumented,
        has_secpolpush=pb.secpolpush_line is not None,
        secpolpush_line=pb.secpolpush_line,
        has_slogger2=pb.has_slogger2,
        services=pb.services,
        libraries=pb.libraries,
        symlinks=[{"target": s["target"], "link": s["link"]} for s in pb.symlinks],
        waitfor_paths=wait_paths,
    )


def _audit_secpol(ps: ParsedSecpol, findings: list[AuditFinding]) -> SecpolSummary:
    fid = [0]

    def add(
        rule_id: str,
        severity: str,
        line: int,
        title: str,
        description: str,
        evidence: str,
        remediation: str,
        standard_ref: str = "QNX SDP 8.0 Security Policies Reference",
        snippet_fix: Optional[str] = None,
    ) -> None:
        fid[0] += 1
        findings.append(
            AuditFinding(
                id=f"SP-{fid[0]:03d}",
                rule_id=rule_id,
                source="secpol",
                severity=severity,  # type: ignore[arg-type]
                line=line,
                title=title,
                description=description,
                evidence=evidence,
                standard_ref=standard_ref,
                remediation=remediation,
                snippet_fix=snippet_fix,
            )
        )

    declared_types: set[str] = set()
    for t in ps.types:
        name = t["name"]
        declared_types.add(name)
        if not VALID_SECPOL_TYPE_RE.match(name):
            add(
                rule_id="QNX8-SECPOL-001",
                severity="CRITICAL",
                line=t["line"],
                title=f"Invalid QNX 8.0 secpol type identifier `{name}`",
                description=(
                    "QNX `secpolcompile` requires type names to start with a letter/underscore and "
                    "contain only alphanumeric characters and underscores (no hyphens or leading digits)."
                ),
                evidence=f"type {name};",
                remediation=f"Rename type to `{re.sub(r'[^A-Za-z0-9_]', '_', name)}`.",
                snippet_fix=f"type {re.sub(r'[^A-Za-z0-9_]', '_', name)};",
            )

    abilities_by_type: dict[str, list[str]] = defaultdict(list)
    trace_holders: list[tuple[str, int]] = []

    for ab in ps.abilities:
        tname = ab["type"]
        ability = ab["ability"]
        line = ab["line"]
        abilities_by_type[tname].append(ability)

        if tname not in declared_types:
            add(
                rule_id="QNX8-SECPOL-008",
                severity="MEDIUM",
                line=line,
                title=f"Ability rule references undeclared type `{tname}`",
                description=f"`allow {tname} self:ability` references `{tname}` without a preceding `type {tname};` declaration.",
                evidence=f"allow {tname} self:ability {{ {ability} }};",
                remediation=f"Add `type {tname};` at the top of the policy file.",
                snippet_fix=f"type {tname};",
            )

        base_ab = ability.split(":", 1)[0]
        has_range = ":" in ability

        # QNX8-SECPOL-002: Unbounded mem_phys
        if base_ab == "mem_phys" and not has_range:
            add(
                rule_id="QNX8-SECPOL-002",
                severity="CRITICAL",
                line=line,
                title=f"Unbounded `mem_phys` physical memory ability on `{tname}`",
                description=(
                    f"Granting unscoped `mem_phys` to `{tname}` allows mapping arbitrary physical RAM / MMIO registers, "
                    "defeating microkernel memory isolation."
                ),
                evidence=f"allow {tname} self:ability {{ ... mem_phys ... }};",
                remediation="Restrict `mem_phys` to the exact MMIO/DMA physical address window (e.g., `mem_phys:0xfeb00000-0xfeb0ffff`).",
                standard_ref="ISO 26262-6 Freedom from Interference (FFI)",
                snippet_fix=f"allow {tname} self:ability {{ mem_phys:0xfeb00000-0xfeb0ffff }};",
            )

        # QNX8-SECPOL-003: Unbounded setuid/setgid
        if base_ab in ("setuid", "setgid") and not has_range:
            add(
                rule_id="QNX8-SECPOL-003",
                severity="CRITICAL",
                line=line,
                title=f"Unbounded `{base_ab}` ability allows root UID escalation on `{tname}`",
                description=(
                    f"`{base_ab}` without an explicit UID/GID range allows `{tname}` to switch to UID 0 (root)."
                ),
                evidence=f"allow {tname} self:ability {{ ... {ability} ... }};",
                remediation=f"Constrain `{base_ab}` to explicit non-root IDs (e.g., `{base_ab}:120`) or remove it and start via `on -U 120:120`.",
                snippet_fix=f"allow {tname} self:ability {{ {base_ab}:120 }};",
            )

        # QNX8-SECPOL-005: Dangerous abilities on runtime or application types
        if base_ab in ("able_create", "xprocess_able", "root"):
            add(
                rule_id="QNX8-SECPOL-005",
                severity="CRITICAL" if base_ab == "root" else "HIGH",
                line=line,
                title=f"Excessive privilege-escalation ability `{ability}` on `{tname}`",
                description=(
                    f"`{base_ab}` lets `{tname}` alter kernel ability tables or run with full root authority, "
                    "undermining least-privilege sandboxing."
                ),
                evidence=f"allow {tname} self:ability {{ ... {ability} ... }};",
                remediation=f"Remove `{ability}` from `{tname}` and enumerate only minimal required non-root abilities.",
            )
        elif tname.endswith("_run_t") and base_ab in DANGEROUS_RUNTIME_ABILITIES:
            add(
                rule_id="QNX8-SECPOL-005",
                severity="HIGH",
                line=line,
                title=f"Post-transition runtime type `{tname}` retains init ability `{ability}`",
                description=(
                    f"`{tname}` is a post-initialization runtime type reached via `secpol_transition_type(NULL, \"run\", 0)`, "
                    f"yet still holds `{ability}` which is only needed during startup."
                ),
                evidence=f"allow {tname} self:ability {{ ... {ability} ... }};",
                remediation=f"Strip `{ability}` from `{tname}` so compromised runtime handlers cannot re-attach paths or escalate privileges.",
            )

        if base_ab == "trace":
            trace_holders.append((tname, line))

    # QNX8-SECPOL-004: Wildcard allow_attach paths
    for ar in ps.attach_rules:
        tname, path, line = ar["type"], ar["path"], ar["line"]
        if tname not in declared_types:
            add(
                rule_id="QNX8-SECPOL-008",
                severity="MEDIUM",
                line=line,
                title=f"`allow_attach` references undeclared type `{tname}`",
                description=f"`allow_attach {tname} {path};` uses undeclared type `{tname}`.",
                evidence=f"allow_attach {tname} {path};",
                remediation=f"Declare `type {tname};` before `allow_attach`.",
            )
        clean_path = path.lstrip("+")
        if clean_path in ("/", "/dev", "/dev/", "/dev/...", "/dev/*", "/*") or clean_path.endswith("/..."):
            add(
                rule_id="QNX8-SECPOL-004",
                severity="CRITICAL",
                line=line,
                title=f"Over-broad `allow_attach` path `{path}` on `{tname}`",
                description=(
                    f"Allowing `{tname}` to attach `{path}` permits hijacking unrelated `/dev/*` resource managers "
                    "(MITM against IPC channels)."
                ),
                evidence=f"allow_attach {tname} {path};",
                remediation=f"Pin `allow_attach` to the exact device node owned by `{tname}` (e.g., `/dev/{tname.removesuffix('_t')}`).",
                standard_ref="QNX 8.0 Pathspace Integrity",
                snippet_fix=f"allow_attach {tname} /dev/{tname.removesuffix('_t')};",
            )

    # QNX8-SECPOL-006: Missing init->runtime type drop split for resource managers
    for tname, abs_list in abilities_by_type.items():
        if tname.endswith("_run_t") or "slogger" in tname:
            continue
        base_set = {a.split(":", 1)[0] for a in abs_list}
        if "pathspace" in base_set or "public_channel" in base_set:
            stem = tname[:-2] if tname.endswith("_t") else tname
            expected_run = f"{stem}_run_t"
            if expected_run not in declared_types:
                add(
                    rule_id="QNX8-SECPOL-006",
                    severity="HIGH",
                    line=next((t["line"] for t in ps.types if t["name"] == tname), 1),
                    title=f"Resource manager `{tname}` lacks post-init runtime type `{expected_run}`",
                    description=(
                        f"`{tname}` holds initialization abilities (`pathspace` / `public_channel`) for its entire lifetime "
                        f"because no `{expected_run}` runtime type is declared for `secpol_transition_type(NULL, \"run\", 0)`."
                    ),
                    evidence=f"type {tname}; abilities: {', '.join(abs_list)}",
                    remediation=(
                        f"Declare `type {expected_run};` with minimal runtime abilities (`nonroot`) and call "
                        "`secpol_transition_type(NULL, \"run\", 0)` right after `resmgr_attach()`."
                    ),
                    standard_ref="QNX 8.0 Privilege Drop Pattern (libsecpol)",
                    snippet_fix=f"type {expected_run};\non_type {tname} run {expected_run};\nallow {expected_run} self:ability {{ nonroot }};",
                )

    # QNX8-SECPOL-007: Trace ability proliferation
    non_telemetry_trace = [(t, ln) for t, ln in trace_holders if "pulse" not in t and "trace" not in t and "diag" not in t]
    for tname, line in non_telemetry_trace:
        add(
            rule_id="QNX8-SECPOL-007",
            severity="MEDIUM",
            line=line,
            title=f"Kernel `trace` ability granted to non-telemetry service `{tname}`",
            description=(
                f"`{tname}` has `PROCMGR_AID_TRACE` (`trace`), which allows reading/modifying global microkernel trace buffers."
            ),
            evidence=f"allow {tname} self:ability {{ ... trace ... }};",
            remediation="Restrict `trace` solely to the dedicated telemetry agent type (e.g., `qnxpulse_t`).",
        )

    secpol_penalty = sum(SEVERITY_PENALTY[f.severity] for f in findings if f.source == "secpol")
    lp_score = max(0, 100 - secpol_penalty)

    return SecpolSummary(
        types=sorted(declared_types),
        abilities_by_type=dict(abilities_by_type),
        attach_rules=[{"type": a["type"], "path": a["path"]} for a in ps.attach_rules],
        channel_rules=[
            {"source": c["source"], "target": c["target"], "object": c["object"], "perms": c["perms"]}
            for c in ps.channel_rules
        ],
        transition_pairs=[
            {"from": tr["from"], "derivation": tr["derivation"], "to": tr["to"]}
            for tr in ps.transitions
        ],
        least_privilege_score=lp_score,
    )


def _cross_check(pb: ParsedBuildfile, ps: ParsedSecpol, findings: list[AuditFinding]) -> None:
    declared = {t["name"] for t in ps.types}
    xc = 0
    for svc in pb.services:
        stype = svc.get("secpol_type")
        if stype and stype not in declared:
            xc += 1
            findings.append(
                AuditFinding(
                    id=f"XC-{xc:03d}",
                    rule_id="QNX8-XCHK-001",
                    source="cross-check",
                    severity="CRITICAL",
                    line=svc["line"],
                    title=f"Buildfile `on -T {stype}` references type missing from secpol",
                    description=(
                        f"Startup script launches `{svc['name']}` with `-T {stype}`, which is not declared "
                        "in the active `.secpol` policy. At boot, `on` will fail to transition and abort service startup."
                    ),
                    evidence=svc["cmd"],
                    standard_ref="QNX 8.0 Buildfile ↔ Secpol Consistency",
                    remediation=f"Declare `type {stype};` (and `{stype.removesuffix('_t')}_run_t`) in your `.secpol` policy before running `secpolcompile`.",
                    snippet_fix=f"type {stype};",
                )
            )
        elif not stype and svc["name"] not in ("ksh", "sh", "pipe"):
            expected = f"{svc['name']}_t"
            if expected not in declared:
                xc += 1
                findings.append(
                    AuditFinding(
                        id=f"XC-{xc:03d}",
                        rule_id="QNX8-XCHK-002",
                        source="cross-check",
                        severity="MEDIUM",
                        line=svc["line"],
                        title=f"Buildfile service `{svc['name']}` has no confinement policy in secpol",
                        description=(
                            f"`{svc['name']}` is launched during boot but has no matching type `{expected}` in the security policy."
                        ),
                        evidence=svc["cmd"],
                        standard_ref="QNX 8.0 Zero-Trust Service Containment",
                        remediation=f"Add `type {expected};` + `{svc['name']}_run_t` and launch via `on -T {expected} -U 120:120`.",
                    )
                )


def _generate_hardened_secpol(pb: Optional[ParsedBuildfile], ps: Optional[ParsedSecpol]) -> str:
    """Synthesize a hardened, least-privilege QNX 8.0 secpol file."""
    lines: list[str] = [
        "# =============================================================================",
        "# QNX SDP 8.0 Hardened Least-Privilege Security Policy",
        "# Auto-generated by QNX-Pulse Security & Boot Auditor",
        "# Compile: secpolcompile -o secpol.bin hardened.secpol",
        "# Enforce: secpolpush -i /proc/boot/secpol.bin (first line of [+script])",
        "# =============================================================================",
        "",
    ]

    type_abilities: dict[str, list[str]] = defaultdict(list)
    attach_by_type: dict[str, list[str]] = defaultdict(list)
    channel_rules: list[dict[str, str]] = []
    all_types: list[str] = []

    if ps:
        for t in ps.types:
            clean = re.sub(r"[^A-Za-z0-9_]", "_", t["name"])
            if clean and clean[0].isdigit():
                clean = "t_" + clean
            if clean not in all_types:
                all_types.append(clean)
        for ab in ps.abilities:
            clean_t = re.sub(r"[^A-Za-z0-9_]", "_", ab["type"])
            raw_ab = ab["ability"]
            base = raw_ab.split(":", 1)[0]
            # Strip dangerous privilege escalation abilities
            if base in ("root", "able_create", "xprocess_able"):
                continue
            if base == "mem_phys" and ":" not in raw_ab:
                raw_ab = "mem_phys:0xfeb00000-0xfeb0ffff"
            elif base == "setuid" and ":" not in raw_ab:
                continue  # Prefer `on -U <uid:gid>` instead of runtime setuid
            elif base == "setgid" and ":" not in raw_ab:
                continue
            elif base == "trace" and not any(k in clean_t for k in ("pulse", "trace", "diag")):
                continue
            if raw_ab not in type_abilities[clean_t]:
                type_abilities[clean_t].append(raw_ab)
        for ar in ps.attach_rules:
            clean_t = re.sub(r"[^A-Za-z0-9_]", "_", ar["type"])
            path = ar["path"]
            clean_p = path.lstrip("+")
            if clean_p in ("/", "/dev", "/dev/", "/dev/...", "/dev/*", "/*") or clean_p.endswith("/..."):
                stem = clean_t.removesuffix("_t")
                path = f"/dev/{stem}"
            if path not in attach_by_type[clean_t]:
                attach_by_type[clean_t].append(path)
        for cr in ps.channel_rules:
            channel_rules.append(cr)

    if pb:
        for svc in pb.services:
            if svc["name"] in ("ksh", "sh", "pipe"):
                continue
            stype = svc.get("secpol_type") or f"{re.sub(r'[^A-Za-z0-9_]', '_', svc['name'])}_t"
            if stype not in all_types:
                all_types.append(stype)
                if "slogger" in stype:
                    type_abilities[stype] = ["nonroot", "pathspace", "public_channel"]
                    attach_by_type[stype] = ["/dev/slog2"]
                else:
                    type_abilities[stype] = ["nonroot", "pathspace", "public_channel"]

    if not all_types:
        all_types = ["qnxpulse_t"]
        type_abilities["qnxpulse_t"] = ["nonroot", "pathspace", "public_channel", "trace"]
        attach_by_type["qnxpulse_t"] = ["/dev/qnxpulse"]

    # Emit base + derived `_run_t` types cleanly
    base_types = [t for t in all_types if not t.endswith("_run_t")]
    for bt in base_types:
        stem = bt[:-2] if bt.endswith("_t") else bt
        run_t = f"{stem}_run_t"
        init_abs = type_abilities.get(bt) or ["nonroot"]
        if "nonroot" not in init_abs:
            init_abs = ["nonroot"] + init_abs

        lines.append(f"# --- Service: {stem} ---")
        lines.append(f"type {bt};")
        needs_run_drop = any(a.split(":", 1)[0] in ("pathspace", "public_channel") for a in init_abs) and "slogger" not in bt
        if needs_run_drop:
            lines.append(f"type {run_t};")
            lines.append(f"on_type {bt} run {run_t};")

        lines.append(f"allow {bt} self:ability {{ {' '.join(init_abs)} }};")
        for p in attach_by_type.get(bt, []):
            lines.append(f"allow_attach {bt} {p};")

        if needs_run_drop:
            # Strip init-only / dangerous abilities from runtime type
            run_abs = [
                a for a in init_abs
                if a.split(":", 1)[0] not in DANGEROUS_RUNTIME_ABILITIES
            ]
            if "nonroot" not in run_abs:
                run_abs.insert(0, "nonroot")
            lines.append(f"allow {run_t} self:ability {{ {' '.join(run_abs)} }};")
        lines.append("")

    if channel_rules:
        lines.append("# --- Explicit IPC Channel Access Rules ---")
        for cr in channel_rules:
            lines.append(f"allow {cr['source']} {cr['target']}:{cr['object']} {cr['perms']};")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def audit_security_and_boot(
    buildfile_text: str = "",
    secpol_text: str = "",
) -> SecurityBootAuditResult:
    """Run full QNX 8.0 `.build` and `.secpol` static audit + auto-hardening diff."""
    findings: list[AuditFinding] = []
    pb: Optional[ParsedBuildfile] = None
    ps: Optional[ParsedSecpol] = None
    bf_summary: Optional[BuildfileSummary] = None
    sp_summary: Optional[SecpolSummary] = None

    if buildfile_text.strip():
        pb = parse_buildfile(buildfile_text)
        bf_summary = _audit_buildfile(pb, findings)

    if secpol_text.strip():
        ps = parse_secpol(secpol_text)
        sp_summary = _audit_secpol(ps, findings)

    if pb is not None and ps is not None:
        _cross_check(pb, ps, findings)

    # Sort findings by severity
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    findings.sort(key=lambda f: (sev_order[f.severity], f.source, f.line))

    penalty = sum(SEVERITY_PENALTY[f.severity] for f in findings)
    overall_score = max(0, min(100, 100 - penalty))
    grade = _compute_grade(overall_score)

    hardened = _generate_hardened_secpol(pb, ps)
    diff_lines = list(
        difflib.unified_diff(
            secpol_text.splitlines(keepends=True) if secpol_text.strip() else [],
            hardened.splitlines(keepends=True),
            fromfile="original.secpol",
            tofile="hardened.secpol",
        )
    )
    hardened_diff = "".join(diff_lines)

    return SecurityBootAuditResult(
        overall_score=overall_score,
        grade=grade,  # type: ignore[arg-type]
        findings=findings,
        buildfile_summary=bf_summary,
        secpol_summary=sp_summary,
        hardened_secpol=hardened,
        hardened_diff=hardened_diff,
    )
