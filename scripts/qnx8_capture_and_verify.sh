#!/bin/sh
# =============================================================================
# QNX-Pulse — QNX SDP 8.0 Target Live-Capture & Verification Kit
# =============================================================================
# Run this script INSIDE your booted QNX 8.0 QEMU x86_64 or Raspberry Pi 5
# target shell (ksh/sh) after booting `qnx8-qemu-x86_64.ifs` or
# `qnx8-rpi5-aarch64.ifs`.
#
# What it verifies and captures:
#   1. Confirms QNX 8.0 instrumented kernel (`procnto-smp-instr`) via uname & pidin
#   2. Verifies `/dev/qnxpulse` Resource Manager is attached & dropped to
#      least-privilege `qnxpulse_run_t` security policy type
#   3. Captures a live kernel trace with `tracelogger` (.kev)
#   4. Converts `.kev` -> human-readable `traceprinter` text (`qnx8_trace.txt`)
#   5. Collects structured `slog2info -S -t` logs (`qnx8_slog2.txt`)
#   6. Prints exact commands to ingest the capture into QNX-Pulse Studio / CLI
# =============================================================================

set -eu

OUT_DIR="${1:-/tmp/qnx_pulse_capture}"
TRACE_SECS="${TRACE_SECS:-3}"
TRACE_BUFS="${TRACE_BUFS:-4}"
KEV_FILE="${OUT_DIR}/qnx8_live.kev"
TRACE_TXT="${OUT_DIR}/qnx8_trace.txt"
SLOG2_TXT="${OUT_DIR}/qnx8_slog2.txt"
AGENT_TXT="${OUT_DIR}/qnxpulse_dev_dump.txt"

mkdir -p "${OUT_DIR}"

echo "====================================================================="
echo " QNX-Pulse Live Capture & Verification Kit (QNX SDP 8.0 Target)"
echo "====================================================================="

echo ""
echo "[1/5] Checking QNX 8.0 kernel & SMP process table..."
uname -a
if command -v pidin >/dev/null 2>&1; then
    pidin info | head -n 12 || true
    echo "--- Active real-time threads (pidin) ---"
    pidin -F "%a %b %N %h %p %J" | head -n 25 || true
else
    echo "WARN: pidin not staged in IFS; skipping process table dump."
fi

echo ""
echo "[2/5] Verifying /dev/qnxpulse Resource Manager & secpol confinement..."
if [ -e /dev/qnxpulse ]; then
    ls -l /dev/qnxpulse
    echo "--- Reading live telemetry snapshot from /dev/qnxpulse ---"
    head -n 20 /dev/qnxpulse > "${AGENT_TXT}" 2>&1 || true
    cat "${AGENT_TXT}"
else
    echo "WARN: /dev/qnxpulse not found. Launch via:"
    echo "      on -T qnxpulse_t -U 120:120 /proc/boot/qnx_pulse_agent &"
fi

if command -v secpol >/dev/null 2>&1 && [ -f /proc/boot/secpol.bin ]; then
    echo "--- Active QNX 8.0 security policy inspection (secpol -i) ---"
    secpol -i /proc/boot/secpol.bin | head -n 30 || true
fi
if command -v pidin >/dev/null 2>&1; then
    echo "--- qnx_pulse_agent security type & UID verification ---"
    pidin -p qnx_pulse_agent -F "%a %N %u %g %p" 2>/dev/null || true
fi

echo ""
echo "[3/5] Capturing live QNX 8.0 kernel event trace (${TRACE_SECS}s, ${TRACE_BUFS} buffers)..."
if command -v tracelogger >/dev/null 2>&1; then
    tracelogger -f "${KEV_FILE}" -n "${TRACE_BUFS}" -s "${TRACE_SECS}"
    ls -lh "${KEV_FILE}"
else
    echo "ERROR: tracelogger not found in PATH. Stage tracelogger & procnto-smp-instr in IFS."
    exit 1
fi

echo ""
echo "[4/5] Converting binary .kev -> QNX 8.0 traceprinter text..."
if command -v traceprinter >/dev/null 2>&1; then
    traceprinter -f "${KEV_FILE}" > "${TRACE_TXT}"
    echo "Converted $(wc -l < "${TRACE_TXT}") traceprinter lines -> ${TRACE_TXT}"
else
    echo "WARN: traceprinter not staged on target; copy ${KEV_FILE} to host and run:"
    echo "      traceprinter -f qnx8_live.kev > qnx8_trace.txt"
fi

echo ""
echo "[5/5] Collecting structured slog2info logs (-S -t)..."
if command -v slog2info >/dev/null 2>&1; then
    slog2info -S -t > "${SLOG2_TXT}" 2>/dev/null || slog2info > "${SLOG2_TXT}" || true
    echo "Collected $(wc -l < "${SLOG2_TXT}") slog2 lines -> ${SLOG2_TXT}"
else
    echo "WARN: slog2info not found; creating empty placeholder."
    : > "${SLOG2_TXT}"
fi

echo ""
echo "====================================================================="
echo " Capture Complete! Artifacts saved under: ${OUT_DIR}"
echo "   - Kernel binary trace : ${KEV_FILE}"
echo "   - Traceprinter dump   : ${TRACE_TXT}"
echo "   - slog2info telemetry : ${SLOG2_TXT}"
echo "   - /dev/qnxpulse dump  : ${AGENT_TXT}"
echo ""
echo " Next step on your Host workstation (after scp/copying files):"
echo "   python -m qnx_pulse.cli analyze --trace qnx8_trace.txt --slog2 qnx8_slog2.txt"
echo "   python -m qnx_pulse.cli audit --build target/qnx_pulse_agent/qnx8-qemu-x86_64.build \\"
echo "                                 --secpol target/qnx_pulse_agent/qnxpulse.secpol"
echo "   # Or paste qnx8_trace.txt into QNX-Pulse Web Studio -> Tab 5 (Upload Trace)"
echo "====================================================================="
