"""Generate authentic QNX SDP 8.0 `traceprinter`, `slog2info`, `mkifs` `.build`, and `.secpol` datasets."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _t(us: float, cycles_per_sec: int, base_cycles: int = 0x01000000) -> str:
    cycles = base_cycles + int(round(us * (cycles_per_sec / 1_000_000.0)))
    return f"t:0x{cycles:08x}"


def generate_adas_aeb() -> None:
    d = ROOT / "adas_aeb_inversion"
    d.mkdir(parents=True, exist_ok=True)
    cps = 2_500_000_000

    meta = {
        "id": "adas_aeb_inversion",
        "name": "Automotive ADAS AEB — IPC Priority Inversion & Deadline Miss",
        "domain": "Automotive SDV (ISO 26262 ASIL-D)",
        "arch": "x86_64 (4-core SMP)",
        "tagline": "10 ms emergency braking deadline missed due to _NTO_CHF_FIXED_PRIORITY on /dev/lidar_fusion",
        "description": (
            "Autonomous Emergency Braking controller (adas_aeb, prio 52, 10 ms deadline) sends synchronous "
            "MsgSend requests to /dev/lidar_fusion (base prio 18). Because lidar_fusion created its channel with "
            "_NTO_CHF_FIXED_PRIORITY, QNX 8.0 kernel priority inheritance is disabled, allowing medium-priority "
            "can_telemetry (prio 30) to preempt lidar_fusion for 10.4 ms and cause a 12.45 ms braking deadline miss."
        ),
        "severity": "CRITICAL",
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    lines = [
        "TRACEPRINTER version 1.05",
        "TRACEPARSER LIBRARY version 1.05",
        "-- HEADER FILE INFORMATION --",
        "TRACE_FILE_NAME:: adas_aeb_inversion.kev",
        "TRACE_DATE:: Thu Nov 19 14:22:10 2026",
        "TRACE_VER_MAJOR:: 1",
        "TRACE_VER_MINOR:: 02",
        "TRACE_LITTLE_ENDIAN:: TRUE",
        "TRACE_ENCODING:: 16 byte events",
        "TRACE_BOOT_DATE:: Thu Nov 19 14:20:00 2026",
        f"TRACE_CYCLES_PER_SEC:: {cps}",
        "TRACE_CPU_NUM:: 4",
        "TRACE_SYSNAME:: QNX",
        "TRACE_NODENAME:: qnx8-adas-ecu",
        "TRACE_SYS_RELEASE:: 8.0.0",
        "TRACE_MACHINE:: x86_64",
        "TRACE_TRACELOGGER_ARGS:: tracelogger -f /tmp/adas_aeb_inversion.kev -n 4 -s 5",
        "",
        "-- KERNEL EVENTS --",
        f"{_t(0, cps)} CPU:00 CONTROL : BUFFER sequence:1 num_events:140",
        f"{_t(5, cps)} CPU:00 PROCESS : PROCCREATE_NAME ppid:1 pid:41370 name:/proc/boot/adas_aeb",
        f"{_t(8, cps)} CPU:00 THREAD  : THCREATE pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(9, cps)} CPU:00 THREAD  : THNAMECREATE pid:41370 tid:1 name:aeb_ctrl",
        f"{_t(12, cps)} CPU:01 PROCESS : PROCCREATE_NAME ppid:1 pid:41371 name:/proc/boot/lidar_fusion",
        f"{_t(15, cps)} CPU:01 THREAD  : THCREATE pid:41371 tid:1 priority:18 policy:FIFO",
        f"{_t(16, cps)} CPU:01 THREAD  : THNAMECREATE pid:41371 tid:1 name:resmgr_worker",
        f"{_t(18, cps)} CPU:01 KER_CALL: CHANNEL_CREATE/25 pid:41371 tid:1 flags:0x0001 flags_name:_NTO_CHF_FIXED_PRIORITY",
        f"{_t(20, cps)} CPU:01 USREVENT: 801 pid:41371 tid:1 resmgr_path:/dev/lidar_fusion chflags:_NTO_CHF_FIXED_PRIORITY",
        f"{_t(22, cps)} CPU:02 PROCESS : PROCCREATE_NAME ppid:1 pid:41372 name:/proc/boot/brake_actuator",
        f"{_t(24, cps)} CPU:02 THREAD  : THCREATE pid:41372 tid:1 priority:48 policy:FIFO",
        f"{_t(25, cps)} CPU:02 THREAD  : THNAMECREATE pid:41372 tid:1 name:can_tx",
        f"{_t(26, cps)} CPU:02 USREVENT: 801 pid:41372 tid:1 resmgr_path:/dev/brake_can",
        f"{_t(28, cps)} CPU:01 PROCESS : PROCCREATE_NAME ppid:1 pid:41373 name:/proc/boot/can_telemetry",
        f"{_t(30, cps)} CPU:01 THREAD  : THCREATE pid:41373 tid:1 priority:30 policy:RR",
        f"{_t(31, cps)} CPU:01 THREAD  : THNAMECREATE pid:41373 tid:1 name:tele_compress",
        f"{_t(33, cps)} CPU:03 PROCESS : PROCCREATE_NAME ppid:1 pid:41374 name:/proc/boot/qnx_pulse_agent",
        f"{_t(35, cps)} CPU:03 THREAD  : THCREATE pid:41374 tid:1 priority:12 policy:RR",
        f"{_t(36, cps)} CPU:03 THREAD  : THNAMECREATE pid:41374 tid:1 name:pulse_mon",
        f"{_t(37, cps)} CPU:03 USREVENT: 801 pid:41374 tid:1 resmgr_path:/dev/qnxpulse",
        "",
        "# --- Frame 1 (Healthy baseline: 1.65 ms < 10.0 ms deadline) ---",
        f"{_t(200, cps)} CPU:00 USREVENT: 810 pid:41370 tid:1 tag:DEADLINE_START frame:1 deadline_us:10000",
        f"{_t(200, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(450, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000101 src_pid:41370 src_tid:1 dst_pid:41371 dst_tid:1",
        f"{_t(465, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000101 pid:41371 tid:1 priority:18",
        f"{_t(470, cps)} CPU:01 THREAD  : THRUNNING pid:41371 tid:1 priority:18 policy:FIFO",
        f"{_t(1250, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000101 pid:41371 tid:1",
        f"{_t(1255, cps)} CPU:01 THREAD  : THRECEIVE pid:41371 tid:1 priority:18",
        f"{_t(1270, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(1450, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000102 src_pid:41370 src_tid:1 dst_pid:41372 dst_tid:1",
        f"{_t(1460, cps)} CPU:02 COMM    : REC_MESSAGE rcvid:0x00000102 pid:41372 tid:1 priority:52",
        f"{_t(1465, cps)} CPU:02 THREAD  : THRUNNING pid:41372 tid:1 priority:52 policy:FIFO",
        f"{_t(1720, cps)} CPU:02 COMM    : REPLY_MESSAGE rcvid:0x00000102 pid:41372 tid:1",
        f"{_t(1725, cps)} CPU:02 THREAD  : THRECEIVE pid:41372 tid:1 priority:48",
        f"{_t(1740, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(1850, cps)} CPU:00 USREVENT: 811 pid:41370 tid:1 tag:DEADLINE_END frame:1",
        f"{_t(1855, cps)} CPU:00 THREAD  : THNANOSLEEP pid:41370 tid:1 priority:52",
        f"{_t(3000, cps)} CPU:03 THREAD  : THRUNNING pid:41374 tid:1 priority:12 policy:RR",
        f"{_t(3150, cps)} CPU:03 COMM    : SND_PULSE_EXE src_pid:41374 dst_pid:41370 code:10",
        f"{_t(3300, cps)} CPU:03 THREAD  : THRECEIVE pid:41374 tid:1 priority:12",
        "",
        "# --- Frame 2 (CRITICAL PRIORITY INVERSION: 12.45 ms > 10.0 ms DEADLINE MISS!) ---",
        f"{_t(10000, cps)} CPU:00 USREVENT: 810 pid:41370 tid:1 tag:DEADLINE_START frame:2 deadline_us:10000",
        f"{_t(10000, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(10220, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000201 src_pid:41370 src_tid:1 dst_pid:41371 dst_tid:1",
        f"{_t(10235, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000201 pid:41371 tid:1 priority:18",
        f"{_t(10240, cps)} CPU:01 THREAD  : THRUNNING pid:41371 tid:1 priority:18 policy:FIFO",
        f"{_t(10420, cps)} CPU:01 THREAD  : THREADY pid:41371 tid:1 priority:18",
        f"{_t(10425, cps)} CPU:01 THREAD  : THRUNNING pid:41373 tid:1 priority:30 policy:RR",
        f"{_t(14500, cps)} CPU:03 THREAD  : THRUNNING pid:41374 tid:1 priority:12 policy:RR",
        f"{_t(14700, cps)} CPU:03 COMM    : SND_PULSE_EXE src_pid:41374 dst_pid:41371 code:11",
        f"{_t(14850, cps)} CPU:03 THREAD  : THRECEIVE pid:41374 tid:1 priority:12",
        f"{_t(20825, cps)} CPU:01 THREAD  : THNANOSLEEP pid:41373 tid:1 priority:30",
        f"{_t(20835, cps)} CPU:01 THREAD  : THRUNNING pid:41371 tid:1 priority:18 policy:FIFO",
        f"{_t(21650, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000201 pid:41371 tid:1",
        f"{_t(21655, cps)} CPU:01 THREAD  : THRECEIVE pid:41371 tid:1 priority:18",
        f"{_t(21675, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(21920, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000202 src_pid:41370 src_tid:1 dst_pid:41372 dst_tid:1",
        f"{_t(21930, cps)} CPU:02 COMM    : REC_MESSAGE rcvid:0x00000202 pid:41372 tid:1 priority:52",
        f"{_t(21935, cps)} CPU:02 THREAD  : THRUNNING pid:41372 tid:1 priority:52 policy:FIFO",
        f"{_t(22280, cps)} CPU:02 COMM    : REPLY_MESSAGE rcvid:0x00000202 pid:41372 tid:1",
        f"{_t(22285, cps)} CPU:02 THREAD  : THRECEIVE pid:41372 tid:1 priority:48",
        f"{_t(22300, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(22450, cps)} CPU:00 USREVENT: 811 pid:41370 tid:1 tag:DEADLINE_END frame:2",
        f"{_t(22455, cps)} CPU:00 THREAD  : THNANOSLEEP pid:41370 tid:1 priority:52",
        "",
        "# --- Frame 3 (Recovery after telemetry burst: 1.78 ms < 10.0 ms deadline) ---",
        f"{_t(24000, cps)} CPU:00 USREVENT: 810 pid:41370 tid:1 tag:DEADLINE_START frame:3 deadline_us:10000",
        f"{_t(24000, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(24210, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000301 src_pid:41370 src_tid:1 dst_pid:41371 dst_tid:1",
        f"{_t(24225, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000301 pid:41371 tid:1 priority:18",
        f"{_t(24230, cps)} CPU:01 THREAD  : THRUNNING pid:41371 tid:1 priority:18 policy:FIFO",
        f"{_t(25120, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000301 pid:41371 tid:1",
        f"{_t(25125, cps)} CPU:01 THREAD  : THRECEIVE pid:41371 tid:1 priority:18",
        f"{_t(25140, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(25310, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000302 src_pid:41370 src_tid:1 dst_pid:41372 dst_tid:1",
        f"{_t(25320, cps)} CPU:02 COMM    : REC_MESSAGE rcvid:0x00000302 pid:41372 tid:1 priority:52",
        f"{_t(25325, cps)} CPU:02 THREAD  : THRUNNING pid:41372 tid:1 priority:52 policy:FIFO",
        f"{_t(25640, cps)} CPU:02 COMM    : REPLY_MESSAGE rcvid:0x00000302 pid:41372 tid:1",
        f"{_t(25645, cps)} CPU:02 THREAD  : THRECEIVE pid:41372 tid:1 priority:48",
        f"{_t(25660, cps)} CPU:00 THREAD  : THRUNNING pid:41370 tid:1 priority:52 policy:FIFO",
        f"{_t(25780, cps)} CPU:00 USREVENT: 811 pid:41370 tid:1 tag:DEADLINE_END frame:3",
        f"{_t(25785, cps)} CPU:00 THREAD  : THNANOSLEEP pid:41370 tid:1 priority:52",
        f"{_t(26500, cps)} CPU:03 THREAD  : THRUNNING pid:41374 tid:1 priority:12 policy:RR",
        f"{_t(26750, cps)} CPU:03 THREAD  : THRECEIVE pid:41374 tid:1 priority:12",
    ]
    (d / "trace.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    slog2 = [
        "Nov 19 14:22:10.001 lidar_fusion.41371 events* INFO 1 100 Attached /dev/lidar_fusion with _NTO_CHF_FIXED_PRIORITY",
        "Nov 19 14:22:10.002 adas_aeb.41370 aeb* INFO 1 200 Frame 1 completed in 1.65 ms (budget 10.00 ms)",
        "Nov 19 14:22:10.011 can_telemetry.41373 tele* WARNING 1 301 Burst compression started on CPU:01 (prio 30 RR)",
        "Nov 19 14:22:10.021 qnx_pulse_agent.41374 watchdog* WARNING 1 901 Priority inversion detected on /dev/lidar_fusion (rcvid=0x201, client_prio=52, server_prio=18)",
        "Nov 19 14:22:10.022 adas_aeb.41370 aeb* CRITICAL 1 299 DEADLINE MISS on Frame 2: 12.45 ms > 10.00 ms budget (+2.45 ms overrun)",
        "Nov 19 14:22:10.026 adas_aeb.41370 aeb* INFO 1 200 Frame 3 recovered in 1.78 ms (budget 10.00 ms)",
    ]
    (d / "slog2.txt").write_text("\n".join(slog2) + "\n", encoding="utf-8")

    build = """# QNX SDP 8.0 Automotive ADAS ECU Buildfile (Pre-Audit / Contains Real Bugs!)
[virtual=x86_64,multiboot] boot = {
    startup-x86 -D 8250
    PATH=/proc/boot:/system/bin
    # Legacy QNX 7 superlocking flag -mL left over during migration
    procnto-smp-instr -mL -v
}

[+script] startup-script = {
    display_msg "Booting ADAS ECU (QNX 8.0)..."
    slogger2 &
    # BUG: lidar_fusion started BEFORE secpolpush and as unconfined root!
    /proc/boot/lidar_fusion &

    display_msg "Pushing security policy (too late!)..."
    secpolpush -i /proc/boot/secpol.bin

    on -T adas_aeb_t -U 110:110 /proc/boot/adas_aeb &
    on -T brake_act_t -U 115:115 /proc/boot/brake_actuator &
    /proc/boot/can_telemetry &
    on -T qnxpulse_t -U 120:120 /proc/boot/qnx_pulse_agent &
}

[uid=0 gid=0]
{
    libc.so
    ksh
    secpolpush
    slogger2
    adas_aeb
    lidar_fusion
    brake_actuator
    can_telemetry
    qnx_pulse_agent
}
"""
    (d / "system.build").write_text(build, encoding="utf-8")

    secpol = """# ADAS ECU QNX 8.0 Security Policy (Pre-Hardening / Over-Privileged)
type adas_aeb_t;
type lidar_fusion_t;
type can_telemetry_t;
type qnxpulse_t;

allow lidar_fusion_t self:ability {
    nonroot
    pathspace
    public_channel
    mem_phys
    setuid
    able_create
};
# Over-broad pathspace wildcard!
allow_attach lidar_fusion_t /dev/...;

allow adas_aeb_t self:ability {
    nonroot
    trace
    priority
};

allow can_telemetry_t self:ability {
    root
    setuid
    trace
};

allow qnxpulse_t self:ability {
    nonroot
    pathspace
    public_channel
    trace
};
allow_attach qnxpulse_t /dev/qnxpulse;
"""
    (d / "system.secpol").write_text(secpol, encoding="utf-8")


def generate_surgical_robot() -> None:
    d = ROOT / "surgical_robot_irq_storm"
    d.mkdir(parents=True, exist_ok=True)
    cps = 2_000_000_000

    meta = {
        "id": "surgical_robot_irq_storm",
        "name": "Medical Surgical Robot — 1 kHz Force-Feedback IRQ Storm",
        "domain": "Medical Robotics (IEC 62304 Class C)",
        "arch": "aarch64 (ARMv8.2 4-core SMP)",
        "tagline": "Unthrottled PCIe Endoscope IRQ 44 routed to CPU:00 causes 1 kHz haptic loop misses",
        "description": (
            "1 kHz surgical manipulator force-feedback loop (kinematics_ctrl, prio 58, 1.0 ms deadline) pinned to CPU:00 "
            "experiences repeated deadline misses when high-bandwidth endoscope DMA interrupts (IRQ 44, ~8.2 kHz) "
            "fire unthrottled on the exact same core instead of being routed to an isolated IST core."
        ),
        "severity": "CRITICAL",
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    lines = [
        "TRACEPRINTER version 1.05",
        "TRACEPARSER LIBRARY version 1.05",
        "-- HEADER FILE INFORMATION --",
        "TRACE_FILE_NAME:: surgical_robot_irq_storm.kev",
        "TRACE_DATE:: Thu Nov 19 16:05:12 2026",
        "TRACE_VER_MAJOR:: 1",
        "TRACE_VER_MINOR:: 02",
        "TRACE_LITTLE_ENDIAN:: TRUE",
        "TRACE_ENCODING:: 16 byte events",
        "TRACE_BOOT_DATE:: Thu Nov 19 16:00:00 2026",
        f"TRACE_CYCLES_PER_SEC:: {cps}",
        "TRACE_CPU_NUM:: 4",
        "TRACE_SYSNAME:: QNX",
        "TRACE_NODENAME:: qnx8-surgical-arm",
        "TRACE_SYS_RELEASE:: 8.0.0",
        "TRACE_MACHINE:: aarch64",
        "TRACE_TRACELOGGER_ARGS:: tracelogger -f /tmp/surgical_irq.kev -n 4 -s 2",
        "",
        "-- KERNEL EVENTS --",
        f"{_t(0, cps)} CPU:00 PROCESS : PROCCREATE_NAME ppid:1 pid:50100 name:/proc/boot/kinematics_ctrl",
        f"{_t(2, cps)} CPU:00 THREAD  : THCREATE pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(3, cps)} CPU:00 THREAD  : THNAMECREATE pid:50100 tid:1 name:torque_loop",
        f"{_t(5, cps)} CPU:01 PROCESS : PROCCREATE_NAME ppid:1 pid:50101 name:/proc/boot/imu_sensor_mgr",
        f"{_t(6, cps)} CPU:01 THREAD  : THCREATE pid:50101 tid:1 priority:54 policy:FIFO",
        f"{_t(7, cps)} CPU:01 THREAD  : THNAMECREATE pid:50101 tid:1 name:spi_resmgr",
        f"{_t(8, cps)} CPU:01 USREVENT: 801 pid:50101 tid:1 resmgr_path:/dev/imu_spi",
        f"{_t(10, cps)} CPU:02 PROCESS : PROCCREATE_NAME ppid:1 pid:50102 name:/proc/boot/endoscope_dma",
        f"{_t(11, cps)} CPU:02 THREAD  : THCREATE pid:50102 tid:1 priority:24 policy:RR",
        f"{_t(12, cps)} CPU:02 THREAD  : THNAMECREATE pid:50102 tid:1 name:dma_worker",
        f"{_t(13, cps)} CPU:02 USREVENT: 801 pid:50102 tid:1 resmgr_path:/dev/video_pcie",
        f"{_t(15, cps)} CPU:03 PROCESS : PROCCREATE_NAME ppid:1 pid:50103 name:/proc/boot/safety_watchdog",
        f"{_t(16, cps)} CPU:03 THREAD  : THCREATE pid:50103 tid:1 priority:60 policy:FIFO",
        f"{_t(17, cps)} CPU:03 THREAD  : THNAMECREATE pid:50103 tid:1 name:wd_mon",
        f"{_t(18, cps)} CPU:03 USREVENT: 801 pid:50103 tid:1 resmgr_path:/dev/safety_wd",
        "",
        "# --- Cycle 1 (Healthy: 320 us < 1000 us deadline) ---",
        f"{_t(100, cps)} CPU:00 USREVENT: 810 pid:50100 tid:1 tag:DEADLINE_START frame:1 deadline_us:1000",
        f"{_t(100, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(190, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000401 src_pid:50100 src_tid:1 dst_pid:50101 dst_tid:1",
        f"{_t(195, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000401 pid:50101 tid:1 priority:58",
        f"{_t(198, cps)} CPU:01 THREAD  : THRUNNING pid:50101 tid:1 priority:58 policy:FIFO",
        f"{_t(280, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000401 pid:50101 tid:1",
        f"{_t(284, cps)} CPU:01 THREAD  : THRECEIVE pid:50101 tid:1 priority:54",
        f"{_t(290, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(420, cps)} CPU:00 USREVENT: 811 pid:50100 tid:1 tag:DEADLINE_END frame:1",
        f"{_t(425, cps)} CPU:00 THREAD  : THNANOSLEEP pid:50100 tid:1 priority:58",
        "",
        "# --- Cycle 2 & 3 (IRQ 44 STORM ON CPU:00 -> DEADLINE MISSES!) ---",
        f"{_t(1100, cps)} CPU:00 USREVENT: 810 pid:50100 tid:1 tag:DEADLINE_START frame:2 deadline_us:1000",
        f"{_t(1100, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
    ]

    # Inject 10 rapid IRQ 44 bursts during Cycle 2 (1140..2260 us)
    t_irq = 1140.0
    for i in range(10):
        lines.append(f"{_t(t_irq, cps)} CPU:00 INT_ENTR:0x0000002c (44) IP:0xffff8000104020")
        lines.append(f"{_t(t_irq + 58, cps)} CPU:00 INT_EXIT:0x0000002c (44)")
        if i == 3:
            lines.append(f"{_t(t_irq + 65, cps)} CPU:02 COMM    : SND_PULSE_EXE src_pid:1 dst_pid:50102 code:44")
            lines.append(f"{_t(t_irq + 70, cps)} CPU:02 THREAD  : THRUNNING pid:50102 tid:1 priority:24 policy:RR")
        t_irq += 115.0

    lines.extend([
        f"{_t(2310, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000402 src_pid:50100 src_tid:1 dst_pid:50101 dst_tid:1",
        f"{_t(2318, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000402 pid:50101 tid:1 priority:58",
        f"{_t(2320, cps)} CPU:01 THREAD  : THRUNNING pid:50101 tid:1 priority:58 policy:FIFO",
        f"{_t(2395, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000402 pid:50101 tid:1",
        f"{_t(2400, cps)} CPU:01 THREAD  : THRECEIVE pid:50101 tid:1 priority:54",
        f"{_t(2408, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(2440, cps)} CPU:00 USREVENT: 811 pid:50100 tid:1 tag:DEADLINE_END frame:2",
        f"{_t(2445, cps)} CPU:00 THREAD  : THNANOSLEEP pid:50100 tid:1 priority:58",
        f"{_t(2455, cps)} CPU:02 THREAD  : THRECEIVE pid:50102 tid:1 priority:24",
        "",
        f"{_t(2550, cps)} CPU:00 USREVENT: 810 pid:50100 tid:1 tag:DEADLINE_START frame:3 deadline_us:1000",
        f"{_t(2550, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
    ])

    # Inject 9 more rapid IRQ 44 bursts during Cycle 3
    t_irq = 2590.0
    for i in range(9):
        lines.append(f"{_t(t_irq, cps)} CPU:00 INT_ENTR:0x0000002c (44) IP:0xffff8000104020")
        lines.append(f"{_t(t_irq + 60, cps)} CPU:00 INT_EXIT:0x0000002c (44)")
        t_irq += 118.0

    lines.extend([
        f"{_t(3680, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000403 src_pid:50100 src_tid:1 dst_pid:50101 dst_tid:1",
        f"{_t(3688, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000403 pid:50101 tid:1 priority:58",
        f"{_t(3690, cps)} CPU:01 THREAD  : THRUNNING pid:50101 tid:1 priority:58 policy:FIFO",
        f"{_t(3770, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000403 pid:50101 tid:1",
        f"{_t(3775, cps)} CPU:01 THREAD  : THRECEIVE pid:50101 tid:1 priority:54",
        f"{_t(3782, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(3890, cps)} CPU:00 USREVENT: 811 pid:50100 tid:1 tag:DEADLINE_END frame:3",
        f"{_t(3895, cps)} CPU:00 THREAD  : THNANOSLEEP pid:50100 tid:1 priority:58",
        f"{_t(3950, cps)} CPU:03 THREAD  : THRUNNING pid:50103 tid:1 priority:60 policy:FIFO",
        f"{_t(4010, cps)} CPU:03 COMM    : SND_PULSE_EXE src_pid:50103 dst_pid:50100 code:99",
        f"{_t(4050, cps)} CPU:03 THREAD  : THRECEIVE pid:50103 tid:1 priority:60",
        "",
        "# --- Cycle 4 (Storm ends: 315 us < 1000 us deadline) ---",
        f"{_t(4200, cps)} CPU:00 USREVENT: 810 pid:50100 tid:1 tag:DEADLINE_START frame:4 deadline_us:1000",
        f"{_t(4200, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(4290, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:0x00000404 src_pid:50100 src_tid:1 dst_pid:50101 dst_tid:1",
        f"{_t(4295, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:0x00000404 pid:50101 tid:1 priority:58",
        f"{_t(4298, cps)} CPU:01 THREAD  : THRUNNING pid:50101 tid:1 priority:58 policy:FIFO",
        f"{_t(4380, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:0x00000404 pid:50101 tid:1",
        f"{_t(4385, cps)} CPU:01 THREAD  : THRECEIVE pid:50101 tid:1 priority:54",
        f"{_t(4392, cps)} CPU:00 THREAD  : THRUNNING pid:50100 tid:1 priority:58 policy:FIFO",
        f"{_t(4515, cps)} CPU:00 USREVENT: 811 pid:50100 tid:1 tag:DEADLINE_END frame:4",
        f"{_t(4520, cps)} CPU:00 THREAD  : THNANOSLEEP pid:50100 tid:1 priority:58",
    ])
    (d / "trace.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    slog2 = [
        "Nov 19 16:05:12.001 kinematics_ctrl.50100 ctrl* INFO 1 100 1 kHz haptic control loop started on CPU:00 (prio 58 FIFO)",
        "Nov 19 16:05:12.002 endoscope_dma.50102 dma* WARNING 1 402 High-rate PCIe DMA burst on IRQ 44 (no coalescing configured)",
        "Nov 19 16:05:12.003 kinematics_ctrl.50100 ctrl* CRITICAL 1 199 DEADLINE MISS Frame 2: 1.34 ms > 1.00 ms budget (ISR preemption storm on CPU:00)",
        "Nov 19 16:05:12.004 safety_watchdog.50103 wd* ERROR 1 501 Two consecutive 1 kHz haptic deadline misses detected; entering damped-torque safeguard",
    ]
    (d / "slog2.txt").write_text("\n".join(slog2) + "\n", encoding="utf-8")

    build = """# QNX SDP 8.0 Surgical Robot Controller Buildfile (Pre-Audit)
[virtual=aarch64le,raw] boot = {
    startup-bcm2712 -D pl011
    PATH=/proc/boot:/system/bin
    LD_LIBRARY_PATH=/proc/boot:/system/lib
    # Non-instrumented kernel prevents live tracelogger capture!
    procnto-smp -v
}

[+script] startup-script = {
    display_msg "Booting Surgical Manipulator..."
    # Missing secpolpush entirely!
    /proc/boot/kinematics_ctrl &
    /proc/boot/imu_sensor_mgr &
    /proc/boot/endoscope_dma &
    /proc/boot/safety_watchdog &
}

[uid=0 gid=0]
{
    libc.so
    kinematics_ctrl
    imu_sensor_mgr
    endoscope_dma
    safety_watchdog
}
"""
    (d / "system.build").write_text(build, encoding="utf-8")

    secpol = """# Surgical Robot Draft Security Policy (Contains Syntax & Privilege Bugs)
type kinematics_ctrl_t;
type endoscope-dma_t;
type imu_sensor_t;

allow endoscope-dma_t self:ability {
    nonroot
    pathspace
    public_channel
    mem_phys
    xprocess_able
    trace
};
allow_attach endoscope-dma_t /dev/*;

allow imu_sensor_t self:ability {
    nonroot
    pathspace
    public_channel
};
allow_attach imu_sensor_t /dev/imu_spi;
"""
    (d / "system.secpol").write_text(secpol, encoding="utf-8")


def generate_amr_healthy() -> None:
    d = ROOT / "amr_fleet_healthy_baseline"
    d.mkdir(parents=True, exist_ok=True)
    cps = 2_500_000_000

    meta = {
        "id": "amr_fleet_healthy_baseline",
        "name": "AMR Autonomous Mobile Robot — Hardened & Tuned QNX 8.0 Baseline",
        "domain": "Autonomous Robotics (Reference Grade-A Baseline)",
        "arch": "x86_64 (4-core SMP)",
        "tagline": "Priority Inheritance enabled + least-privilege secpol (_run_t) + sub-650 us deterministic latency",
        "description": (
            "Properly engineered QNX 8.0 SMP robotics stack: /dev/lidar_fusion uses default ChannelCreate(0) so "
            "motion_planner (prio 52) boosts lidar_fusion from prio 18 -> 52 automatically during MsgSend/MsgReply, "
            "preventing fleet_telemetry (prio 28) preemption. IFS boots procnto-smp-instr with early secpolpush and "
            "post-init secpol_transition_type(NULL, \"run\", 0) privilege drops (Grade A, 100/100)."
        ),
        "severity": "HEALTHY",
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    lines = [
        "TRACEPRINTER version 1.05",
        "TRACEPARSER LIBRARY version 1.05",
        "-- HEADER FILE INFORMATION --",
        "TRACE_FILE_NAME:: amr_fleet_healthy_baseline.kev",
        "TRACE_DATE:: Thu Nov 19 17:10:00 2026",
        "TRACE_VER_MAJOR:: 1",
        "TRACE_VER_MINOR:: 02",
        "TRACE_LITTLE_ENDIAN:: TRUE",
        "TRACE_ENCODING:: 16 byte events",
        "TRACE_BOOT_DATE:: Thu Nov 19 17:08:00 2026",
        f"TRACE_CYCLES_PER_SEC:: {cps}",
        "TRACE_CPU_NUM:: 4",
        "TRACE_SYSNAME:: QNX",
        "TRACE_NODENAME:: qnx8-amr-07",
        "TRACE_SYS_RELEASE:: 8.0.0",
        "TRACE_MACHINE:: x86_64",
        "TRACE_TRACELOGGER_ARGS:: tracelogger -f /tmp/amr_healthy.kev -n 4 -s 5",
        "",
        "-- KERNEL EVENTS --",
        f"{_t(0, cps)} CPU:00 PROCESS : PROCCREATE_NAME ppid:1 pid:60200 name:/proc/boot/motion_planner",
        f"{_t(3, cps)} CPU:00 THREAD  : THCREATE pid:60200 tid:1 priority:52 policy:FIFO",
        f"{_t(4, cps)} CPU:00 THREAD  : THNAMECREATE pid:60200 tid:1 name:mpc_loop",
        f"{_t(6, cps)} CPU:01 PROCESS : PROCCREATE_NAME ppid:1 pid:60201 name:/proc/boot/lidar_fusion",
        f"{_t(8, cps)} CPU:01 THREAD  : THCREATE pid:60201 tid:1 priority:18 policy:FIFO",
        f"{_t(9, cps)} CPU:01 THREAD  : THNAMECREATE pid:60201 tid:1 name:resmgr_worker",
        f"{_t(10, cps)} CPU:01 KER_CALL: CHANNEL_CREATE/25 pid:60201 tid:1 flags:0x0000",
        f"{_t(11, cps)} CPU:01 USREVENT: 801 pid:60201 tid:1 resmgr_path:/dev/lidar_fusion",
        f"{_t(13, cps)} CPU:02 PROCESS : PROCCREATE_NAME ppid:1 pid:60202 name:/proc/boot/motor_drive_mgr",
        f"{_t(14, cps)} CPU:02 THREAD  : THCREATE pid:60202 tid:1 priority:50 policy:FIFO",
        f"{_t(15, cps)} CPU:02 THREAD  : THNAMECREATE pid:60202 tid:1 name:drive_tx",
        f"{_t(16, cps)} CPU:02 USREVENT: 801 pid:60202 tid:1 resmgr_path:/dev/motor_can",
        f"{_t(18, cps)} CPU:01 PROCESS : PROCCREATE_NAME ppid:1 pid:60203 name:/proc/boot/fleet_telemetry",
        f"{_t(19, cps)} CPU:01 THREAD  : THCREATE pid:60203 tid:1 priority:28 policy:RR",
        f"{_t(20, cps)} CPU:01 THREAD  : THNAMECREATE pid:60203 tid:1 name:mqtt_tx",
        f"{_t(22, cps)} CPU:03 PROCESS : PROCCREATE_NAME ppid:1 pid:60204 name:/proc/boot/qnx_pulse_agent",
        f"{_t(23, cps)} CPU:03 THREAD  : THCREATE pid:60204 tid:1 priority:14 policy:RR",
        f"{_t(24, cps)} CPU:03 THREAD  : THNAMECREATE pid:60204 tid:1 name:pulse_mon",
        f"{_t(25, cps)} CPU:03 USREVENT: 801 pid:60204 tid:1 resmgr_path:/dev/qnxpulse",
    ]

    # 4 deterministic 5 ms cycles, all completing in ~520-610 us with Priority Inheritance boosting 18 -> 52!
    for frame in range(1, 5):
        base = (frame - 1) * 5000.0 + 200.0
        jitter = (frame % 3) * 28.0
        rcvid1 = f"0x00000{frame}01"
        rcvid2 = f"0x00000{frame}02"
        lines.extend([
            f"",
            f"# --- Cycle {frame} (Priority Inheritance boosts lidar_fusion 18 -> 52!) ---",
            f"{_t(base, cps)} CPU:00 USREVENT: 810 pid:60200 tid:1 tag:DEADLINE_START frame:{frame} deadline_us:5000",
            f"{_t(base, cps)} CPU:00 THREAD  : THRUNNING pid:60200 tid:1 priority:52 policy:FIFO",
            f"{_t(base + 110, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:{rcvid1} src_pid:60200 src_tid:1 dst_pid:60201 dst_tid:1",
            # Boosted immediately to priority 52 by QNX 8.0 kernel!
            f"{_t(base + 118, cps)} CPU:01 COMM    : REC_MESSAGE rcvid:{rcvid1} pid:60201 tid:1 priority:52",
            f"{_t(base + 120, cps)} CPU:01 THREAD  : THRUNNING pid:60201 tid:1 priority:52 policy:FIFO",
            # Telemetry tries to wake, stays READY behind prio-52 boosted lidar_fusion
            f"{_t(base + 180, cps)} CPU:01 THREAD  : THREADY pid:60203 tid:1 priority:28",
            f"{_t(base + 320 + jitter, cps)} CPU:01 COMM    : REPLY_MESSAGE rcvid:{rcvid1} pid:60201 tid:1",
            f"{_t(base + 325 + jitter, cps)} CPU:01 THREAD  : THRECEIVE pid:60201 tid:1 priority:18",
            # Now telemetry safely runs on CPU:01 without delaying motion_planner!
            f"{_t(base + 330 + jitter, cps)} CPU:01 THREAD  : THRUNNING pid:60203 tid:1 priority:28 policy:RR",
            f"{_t(base + 335 + jitter, cps)} CPU:00 THREAD  : THRUNNING pid:60200 tid:1 priority:52 policy:FIFO",
            f"{_t(base + 410 + jitter, cps)} CPU:00 COMM    : SND_MESSAGE rcvid:{rcvid2} src_pid:60200 src_tid:1 dst_pid:60202 dst_tid:1",
            f"{_t(base + 418 + jitter, cps)} CPU:02 COMM    : REC_MESSAGE rcvid:{rcvid2} pid:60202 tid:1 priority:52",
            f"{_t(base + 420 + jitter, cps)} CPU:02 THREAD  : THRUNNING pid:60202 tid:1 priority:52 policy:FIFO",
            f"{_t(base + 510 + jitter, cps)} CPU:02 COMM    : REPLY_MESSAGE rcvid:{rcvid2} pid:60202 tid:1",
            f"{_t(base + 514 + jitter, cps)} CPU:02 THREAD  : THRECEIVE pid:60202 tid:1 priority:50",
            f"{_t(base + 520 + jitter, cps)} CPU:00 THREAD  : THRUNNING pid:60200 tid:1 priority:52 policy:FIFO",
            f"{_t(base + 565 + jitter, cps)} CPU:00 USREVENT: 811 pid:60200 tid:1 tag:DEADLINE_END frame:{frame}",
            f"{_t(base + 570 + jitter, cps)} CPU:00 THREAD  : THNANOSLEEP pid:60200 tid:1 priority:52",
            f"{_t(base + 1400, cps)} CPU:01 THREAD  : THNANOSLEEP pid:60203 tid:1 priority:28",
            f"{_t(base + 2000, cps)} CPU:03 THREAD  : THRUNNING pid:60204 tid:1 priority:14 policy:RR",
            f"{_t(base + 2180, cps)} CPU:03 COMM    : SND_PULSE_EXE src_pid:60204 dst_pid:60200 code:10",
            f"{_t(base + 2250, cps)} CPU:03 THREAD  : THRECEIVE pid:60204 tid:1 priority:14",
        ])

    (d / "trace.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    slog2 = [
        "Nov 19 17:10:00.001 lidar_fusion.60201 events* INFO 1 100 Attached /dev/lidar_fusion (priority inheritance active); transitioned to lidar_fusion_run_t",
        "Nov 19 17:10:00.002 motion_planner.60200 mpc* INFO 1 200 Cycle 1 complete in 593 us (budget 5000 us)",
        "Nov 19 17:10:00.007 motion_planner.60200 mpc* INFO 1 200 Cycle 2 complete in 621 us (budget 5000 us)",
        "Nov 19 17:10:00.012 qnx_pulse_agent.60204 monitor* INFO 1 900 Real-time invariants nominal: 0 inversions, 0 misses",
    ]
    (d / "slog2.txt").write_text("\n".join(slog2) + "\n", encoding="utf-8")

    build = """# QNX SDP 8.0 Hardened AMR Robotics Buildfile (Grade A Reference)
[virtual=x86_64,multiboot] boot = {
    startup-x86 -D 8250
    PATH=/proc/boot:/system/bin
    LD_LIBRARY_PATH=/proc/boot:/system/lib:/system/lib/dll
    procnto-smp-instr -v
}

[+script] startup-script = {
    display_msg "Enforcing QNX 8.0 security policy..."
    secpolpush -i /proc/boot/secpol.bin

    on -T slogger2_t -U 21:21 /proc/boot/slogger2 &
    waitfor /dev/slog2 4

    on -T lidar_fusion_t -U 110:110 /proc/boot/lidar_fusion &
    waitfor /dev/lidar_fusion 4

    on -T motor_drive_mgr_t -U 112:112 /proc/boot/motor_drive_mgr &
    waitfor /dev/motor_can 4

    on -T motion_planner_t -U 114:114 /proc/boot/motion_planner &
    on -T fleet_telemetry_t -U 118:118 /proc/boot/fleet_telemetry &
    on -T qnxpulse_t -U 120:120 /proc/boot/qnx_pulse_agent &
    waitfor /dev/qnxpulse 4

    procmgr_symlink /proc/boot/ksh /bin/sh
    display_msg "AMR QNX 8.0 Boot Complete."
}

[uid=0 gid=0]
{
    libc.so
    libslog2.so
    libsecpol.so
    ksh
    secpolpush
    secpol.bin={./secpol.bin}
    slogger2
    lidar_fusion
    motor_drive_mgr
    motion_planner
    fleet_telemetry
    qnx_pulse_agent
}
"""
    (d / "system.build").write_text(build, encoding="utf-8")

    secpol = """# QNX SDP 8.0 Hardened AMR Robotics Security Policy (Grade A Reference)
type slogger2_t;
allow slogger2_t self:ability { nonroot pathspace public_channel };
allow_attach slogger2_t /dev/slog2;

type lidar_fusion_t;
type lidar_fusion_run_t;
on_type lidar_fusion_t run lidar_fusion_run_t;
allow lidar_fusion_t self:ability { nonroot pathspace public_channel };
allow_attach lidar_fusion_t /dev/lidar_fusion;
allow lidar_fusion_run_t self:ability { nonroot };

type motor_drive_mgr_t;
type motor_drive_mgr_run_t;
on_type motor_drive_mgr_t run motor_drive_mgr_run_t;
allow motor_drive_mgr_t self:ability { nonroot pathspace public_channel mem_phys:0xfeb00000-0xfeb0ffff };
allow_attach motor_drive_mgr_t /dev/motor_can;
allow motor_drive_mgr_run_t self:ability { nonroot mem_phys:0xfeb00000-0xfeb0ffff };

type motion_planner_t;
allow motion_planner_t self:ability { nonroot priority };

type fleet_telemetry_t;
allow fleet_telemetry_t self:ability { nonroot };

type qnxpulse_t;
type qnxpulse_run_t;
on_type qnxpulse_t run qnxpulse_run_t;
allow qnxpulse_t self:ability { nonroot pathspace public_channel trace };
allow_attach qnxpulse_t /dev/qnxpulse;
allow qnxpulse_run_t self:ability { nonroot trace };
"""
    (d / "system.secpol").write_text(secpol, encoding="utf-8")


if __name__ == "__main__":
    generate_adas_aeb()
    generate_surgical_robot()
    generate_amr_healthy()
    print("Generated all 3 QNX 8.0 benchmark datasets successfully.")
