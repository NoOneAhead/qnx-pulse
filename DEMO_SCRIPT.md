# QNX-Pulse — YouTube Demo Video Script (Target Runtime: 2m 35s)

> **Competition Rule:** Must be **under 3 minutes**, in **English**, demonstrating working software and authentic QNX 8.0 capabilities.
> **Recommended Recording Setup:** 1920×1080 @ 30fps, browser at `http://127.0.0.1:8080/` + terminal side-by-side (or clean tab switch).

---

## Scene 1: The Problem & Hook (0:00 – 0:25)
- **Visual:** Start on **QNX-Pulse Mission Control Studio** (`http://127.0.0.1:8080/`) showing the `Automotive ADAS AEB — IPC Priority Inversion & Deadline Miss` scenario with the pulsing crimson `RT Health: 50/100` pill and Gantt chart.
- **Voiceover:**
  > "In safety-critical automotive ADAS and surgical robotics, QNX 8.0's microkernel gives us rock-solid real-time determinism and least-privilege `secpol` isolation. Yet one accidental `_NTO_CHF_FIXED_PRIORITY` flag in a Resource Manager, or one misordered `secpolpush` line in an IFS `.build` file, can cause a catastrophic 10-millisecond braking deadline miss. Today we're introducing **QNX-Pulse** — an open-source QNX 8.0 Microkernel Trace, IPC Topology, Buildfile & Secpol Studio."

---

## Scene 2: Real-Time Scheduler Gantt & Priority Inversion Detection (0:25 – 0:55)
- **Visual:**
  - Hover over the crimson **PI-001 INVERSION (11.43 ms)** band on the SVG Scheduler Gantt Chart.
  - Click **2× Zoom** to clearly show `adas_aeb` (prio 52) stuck in `REPLY BLOCKED` while `can_telemetry` (prio 30) preempts `lidar_fusion` (prio 18).
  - Scroll briefly past the **Per-Core SMP Utilization**, **Latency Histogram**, **Threads Table** (pointing out `brake_actuator` cleanly boosted `48 → 52 (PI)` while `lidar_fusion` stayed flat at `18`), and correlated `slog2info` feed.
- **Voiceover:**
  > "QNX-Pulse ingests authentic QNX 8.0 `traceprinter` dumps and `slog2info` logs. Here on our 4-core x86_64 ADAS ECU trace, QNX-Pulse immediately pinpoints **PI-001**: `adas_aeb` at priority 52 blocked for 11.4 milliseconds on `/dev/lidar_fusion` because its channel disabled priority inheritance with `_NTO_CHF_FIXED_PRIORITY`, letting medium-priority `can_telemetry` preempt it and trigger a 12.45 millisecond deadline miss."

---

## Scene 3: IPC Topology & Surgical Robot IRQ Storm Contrast (0:55 – 1:20)
- **Visual:**
  - Click **Tab 2: IPC & Resmgr Topology** — click the glowing red `adas_aeb → lidar_fusion` edge to show `Priority Inheritance: DISABLED (_NTO_CHF_FIXED_PRIORITY)` in the Inspector.
  - Switch the top Scenario dropdown to **Medical Surgical Robot — 1 kHz Force-Feedback IRQ Storm** -> show **Tab 1** highlighting **IRQ-001** (IRQ 44 firing at 7,742 Hz on `CPU:00`, consuming 24.8% CPU and causing two 1 kHz haptic deadline misses).
- **Voiceover:**
  > "In the IPC Topology view, we map every synchronous `MsgSend`/`MsgReply` channel and `/dev/*` Resource Manager path — immediately exposing the inverted channel. Switch to our ARMv8 surgical robotics trace, and QNX-Pulse catches an entirely different class of failure: an unthrottled PCIe IRQ 44 storm saturating `CPU:00` and starving the 1-kilohertz force-feedback loop."

---

## Scene 4: Live QNX 8.0 Buildfile & Secpol Auditor + One-Click Auto-Hardener (1:20 – 1:55)
- **Visual:**
  - Switch back to `adas_aeb_inversion` and open **Tab 3: Buildfile & Secpol Auditor**.
  - Scroll through findings: `QNX8-BUILD-004` (late `secpolpush`), `QNX8-BUILD-002` (deprecated QNX 7 `-mL` superlock flag), `QNX8-SECPOL-002/004/006` (unbounded `mem_phys`, wildcard `/dev/...`, missing `_run_t` runtime drop types).
  - Click **"Apply Auto-Hardened Secpol →"** — show the live editor update, unified diff, and score jumping immediately!
  - Briefly show **Tab 4: Diagnostic Copilot** (offline deterministic C code patch) and **Tab 5: Export ISO 26262 ASIL-D Report**.
- **Voiceover:**
  > "Next, our static Buildfile and `secpol` auditor enforces 18 QNX 8.0-specific rules — catching deprecated QNX 7 superlocking flags, late `secpolpush`, unbounded `mem_phys`, and missing post-init `_run_t` types for `secpol_transition_type`. One click applies our auto-hardened least-privilege policy, and our offline Diagnostic Copilot generates exact C remediation patches alongside exportable ISO 26262 and IEC 62304 compliance reports."

---

## Scene 5: Authentic QNX 8.0 C Resource Manager + Interactive Codelab (1:55 – 2:35)
- **Visual:**
  - Quick terminal shot (10s): show `target/qnx_pulse_agent/src/qnx_pulse_agent.c` (`resmgr_attach`, `TraceEvent`, `secpol_transition_type`, `procmgr_ability`), run `./test_telemetry_ring` (7/7 PASS) and pipe `./qnx_pulse_agent_sim --scenario inversion` directly into `qnx-pulse analyze` catching `PI-001`!
  - Switch browser tab to **QNX 8.0 Codelab** (`http://127.0.0.1:8080/codelab/`), jump to **Step 6**, and toggle the **Interactive Priority Inheritance Simulator** from `BUGGY (_NTO_CHF_FIXED_PRIORITY)` → `FIXED (QNX 8.0 Priority Inheritance)` watching the braking cycle drop from `12.45 ms MISS` to `1.4 ms PASS`!
  - End on the `AMR Healthy Baseline (100/100 Grade A)` screen.
- **Voiceover:**
  > "Under the hood, we also ship a real C11 QNX 8.0 Resource Manager at `/dev/qnxpulse` with a lock-free telemetry ring buffer, `qcc` and CMake toolchains, QEMU x86_64 and Raspberry Pi 5 `.build` files, and a host-verified simulation mode that pipes straight into QNX-Pulse. And to help new developers master QNX 8.0 fast, we built a standalone, GitHub-Pages-ready interactive Codelab — complete with a live Priority Inheritance simulator. QNX-Pulse is MIT-licensed and ready to run today. Thanks for watching!"
