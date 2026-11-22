# QNX Global Hackathon 2026 — Devpost Submission Package

> Ready-to-paste Devpost form fields + final pre-submission handoff checklist.

---

## 1. Devpost Submission Fields

### Project Name
**QNX-Pulse — QNX 8.0 Microkernel Trace, IPC Topology, Buildfile & Secpol Studio**

### Tagline (max 200 chars)
Pinpoint QNX 8.0 IPC priority inversions, IRQ storms, mkifs boot races, and secpol flaws in seconds — with a host Mission Control Studio, CI CLI, native C `/dev/qnxpulse` agent, and interactive Codelab.

### Category & Bonus Tracks
- **Primary Category:** Developer Tooling & Host Tools ($4,000 Best of Category / $2,000 Runner-Up + $10,000 Grand Prize)
- **Bonus Track 1:** Best use of QNX-specific Technologies ($3,500)
- **Bonus Track 2:** Best Codelab / Tutorial ($3,500) — hosted from `codelab/index.html` on GitHub Pages

### Built With (Tags)
`qnx-8.0`, `c`, `python`, `fastapi`, `javascript`, `svg`, `cmake`, `mkifs`, `secpol`, `tracelogger`, `qemu`

---

### Inspiration
Engineers building Automotive ADAS (ISO 26262 ASIL-D), Medical Surgical Robotics (IEC 62304 Class C), and Industrial AMR platforms choose **QNX OS 8.0** for its microkernel determinism, kernel-enforced `MsgSend`/`MsgReply` priority inheritance, and mandatory `secpol` containment. Yet debugging a real-time deadline miss still means manually grepping thousands of `traceprinter` lines, cross-referencing `slog2info`, inspecting `mkifs` `.build` boot ordering by eye, and hand-auditing `secpol` ability blocks.

We built **QNX-Pulse** to give every QNX 8.0 developer an instant, offline-first Mission Control workbench — plus a lightweight native QNX 8.0 C Resource Manager (`/dev/qnxpulse`) and a hands-on interactive QNX 8.0 Codelab.

### What It Does
1. **QNX 8.0 Microkernel Trace & Real-Time Analyzer (`qnx_pulse/parsers/traceprinter.py`, `analyzers/realtime.py`)**
   - Parses authentic QNX 8.0 `traceprinter` (`.kev` dumps) and `slog2info` logs.
   - Computes per-thread WCET, p50/p95/p99 latency, jitter, CPU share, per-core SMP & IRQ utilization, and latency distribution histograms.
   - Automatically detects **QNX 8.0 IPC priority inversions** (pinpointing `_NTO_CHF_FIXED_PRIORITY` channels where a server failed to inherit client priority and was preempted by medium-priority work), **hardware IRQ storms**, and **correlated deadline misses**.
2. **Interactive IPC & Resource Manager Topology (`analyzers/ipc_topology.py`)**
   - Reconstructs the directed process graph of synchronous `MsgSend`/`MsgReply` channels, asynchronous `MsgSendPulse` flows, and `/dev/*` resource manager paths — visually highlighting priority-inversion hotspots vs. healthy kernel-boosted channels.
3. **QNX 8.0 IFS `.build` & `secpol` Static Security/Boot Auditor + Auto-Hardener (`analyzers/security_boot.py`)**
   - Audits 18 authentic QNX 8.0 rules: non-instrumented `procnto-smp`, deprecated QNX 7 `-mL` superlocking flags, missing/late `secpolpush`, `waitfor /dev/slog2` boot races, invalid secpol identifiers, unbounded `mem_phys`/`setuid`, wildcard `allow_attach /dev/...`, missing `_run_t` post-init privilege-drop types, and cross-checks `on -T <type>` against `.secpol`.
   - One-click **Auto-Hardener** generates a hardened least-privilege QNX 8.0 `.secpol` policy + unified diff (automatically creating `*_run_t` transition types for `secpol_transition_type(NULL, "run", 0)`).
4. **Offline Deterministic + Optional BYO-LLM Diagnostic Copilot & Compliance Exporter**
   - Synthesizes root causes, prioritized action plans, and copyable QNX 8.0 C / `.build` / `.secpol` patches 100% offline (with optional OpenAI/Anthropic/Ollama key support).
   - Exports ISO 26262 ASIL-D / IEC 62304 Class C / IEC 61508 SIL-3 verification packages in Markdown or JSON, plus CI regression gates (`qnx-pulse analyze --fail-on-critical`).
5. **Authentic QNX 8.0 Target Companion Agent in C (`target/qnx_pulse_agent/`)**
   - Real C11 QNX 8.0 Resource Manager (`/dev/qnxpulse`) using `<sys/neutrino.h>`, `<sys/dispatch.h>`, `<sys/iofunc.h>`, `<sys/procmgr.h>`, `<sys/trace.h>`, `<sys/slog2.h>`, `<secpol/secpol.h>`, and `<devctl.h>`.
   - Zero-heap C11 `<stdatomic.h>` lock-free telemetry ring buffer, inline IPC priority-inversion watchdog, `secpol_transition_type(NULL, "run", 0)` + locked `procmgr_ability` fallback, `qcc` `Makefile`, `qnx800.toolchain.cmake`, QEMU x86_64 & Raspberry Pi 5 aarch64 `.build` files, and a host-compilable simulator + C test suite verified with `gcc -Wall -Wextra -Werror`.
6. **Standalone Interactive QNX 8.0 Codelab (`codelab/`)**
   - GitHub-Pages-ready 7-step tutorial teaching QNX 8.0 `mkifs`, Resource Managers, `secpol` hardening, `tracelogger`/`traceprinter`, and fixing a real `_NTO_CHF_FIXED_PRIORITY` priority inversion — complete with an embedded interactive SVG Priority Inheritance Simulator, 4-question comprehension quiz, and ready-to-compile QNX 8.0 `lab_files/`.

### How We Built It
- **Host Workbench & CLI:** Python 3.13, FastAPI, Pydantic v2, Typer, Rich, and a zero-build-friction dark-industrial HTML5/CSS3/ES6 SVG Mission Control UI (Gantt scheduler, directed IPC graph, live code editors, unified diff viewer).
- **Target Companion:** Pure C11 with `#ifdef __QNX__` QNX SDP 8.0 native Resource Manager implementation and host-simulation portability verified under GCC 16 (`-std=c11 -Wall -Wextra -Werror`) and CMake/CTest.
- **Codelab:** Standalone static HTML/CSS/JS + Markdown edition deployable to GitHub Pages with zero external runtime dependencies.

### Challenges We Ran Into
- Matching real QNX 8.0 `traceprinter` timestamp/event variants (hex cycle counts scaled by `TRACE_CYCLES_PER_SEC`, inline `INT_ENTR`/`INT_EXIT`, and single-PID vs dual-PID `COMM` lines from both `traceprinter` and our C companion agent).
- Catching subtle QNX 8.0 `mkifs` syntax forms (such as inline `PATH=... LD_LIBRARY_PATH=... procnto-smp-instr -v` and `[+session] ksh &`) and QNX 8.0 `secpol` transition keywords (`derive_type` / `on_type`).
- Verifying our `#ifdef __QNX__` C code path strictly under `-std=c11 -Wall -Wextra -Werror` alongside the host simulator and end-to-end C-to-Python trace pipeline.

### Accomplishments We're Proud Of
- True end-to-end C-to-Python loop: compiling and running our C target companion agent in host-simulation mode streams authentic `traceprinter` events directly into QNX-Pulse, which detects the exact `_NTO_CHF_FIXED_PRIORITY` priority inversion!
- Clicking **"Apply Auto-Hardened Secpol"** live in the UI transforms a Grade F (0/100) automotive policy into a least-privilege QNX 8.0 policy with derived `_run_t` runtime types in one click.
- Shipping a complete, standalone, interactive QNX 8.0 Codelab with an embedded Priority Inheritance Gantt Simulator.

### What's Next for QNX-Pulse
- Live SSH / QConn (`qconn`) remote streaming directly from `/dev/qnxpulse` on Raspberry Pi 5 & QEMU targets into the Web UI via WebSockets.
- Binary `.kev` direct reader (bypassing the `traceprinter` text conversion step) and Adaptive Partitioning Scheduler (APS) budget analyzer for QNX 8.0.

---

## 2. Final Manual Handoff Checklist for User

> The repository is already initialized on `main` with a clean commit, verified MIT `LICENSE`, 512×512 logo (`docs/images/qnx-pulse-logo.png`), 4 embedded UI screenshots (`docs/images/qnx_pulse_*.png`), GitHub Actions CI + Codelab Pages auto-deploy workflow (`.github/workflows/ci-and-pages.yml`), QNX 8.0 target capture kit (`scripts/qnx8_capture_and_verify.sh`), and single-command pre-submission verifier (`python scripts/verify_submission.py`).

1. **Public GitHub Repository**:
   - Repository URL: `https://github.com/NoOneAhead/qnx-pulse`
2. **Live GitHub Pages Codelab (Auto-Deployed by `.github/workflows/ci-and-pages.yml`)**:
   - Live Codelab URL: `https://nooneahead.github.io/qnx-pulse/` (for the **$3,500 Best Codelab / Tutorial** bonus prize).
3. **(Optional — Recommended for Extra Judging Polish) Compile, Boot & Capture on QNX SDP 8.0 QEMU**:
   - Sign in to your free QNX Everywhere account, install QNX SDP 8.0, source `qnxsdp-env.sh`, and run:
     ```bash
     cd target/qnx_pulse_agent && make qnx-x86_64 secpol ifs-qemu-x86_64
     qemu-system-x86_64 -M q35 -smp 2 -m 1G -nographic -kernel build/qnx8-qemu-x86_64.ifs
     ```
   - Inside the booted QNX 8.0 shell, run `sh scripts/qnx8_capture_and_verify.sh` to verify `/dev/qnxpulse` + `secpol` + capture real `.kev` / `traceprinter` / `slog2info` artifacts!
4. **Demo Video & Devpost Gallery**:
   - **Public YouTube Demo Video (`02:28`, 1080p HD):** `https://youtu.be/rv_Hrj68xYY`
   - Upload `docs/images/qnx-pulse-logo.png` as the Devpost project thumbnail and the 4 screenshots in `docs/images/` into the Devpost image gallery.
   - Submit on Devpost (`https://qnx.devpost.com/`) before **Dec 15, 2026 @ 2:00 PM ET**.
