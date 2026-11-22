"""Unit tests for QNX 8.0 traceprinter, slog2info, mkifs buildfile, and secpol parsers."""

from qnx_pulse.parsers import (
    parse_buildfile,
    parse_secpol,
    parse_slog2,
    parse_traceprinter,
)


def test_parse_traceprinter_headers_and_events():
    sample = """
TRACEPRINTER version 1.05
TRACE_FILE_NAME:: test_qnx8.kev
TRACE_CYCLES_PER_SEC:: 2500000000
TRACE_CPU_NUM:: 4
TRACE_SYSNAME:: QNX
TRACE_SYS_RELEASE:: 8.0.0
TRACE_MACHINE:: x86_64
-- KERNEL EVENTS --
t:0x01000000 CPU:00 PROCESS : PROCCREATE_NAME ppid:1 pid:100 name:/proc/boot/adas_aeb
t:0x010009c4 CPU:00 THREAD  : THRUNNING pid:100 tid:1 priority:52 policy:FIFO
t:0x01001388 CPU:01 COMM    : SND_MESSAGE rcvid:0x1 src_pid:100 src_tid:1 dst_pid:101 dst_tid:1
t:0x01001d4c CPU:00 INT_ENTR:0x0000002c (44) IP:0xb8229890
t:0x01001f40 CPU:00 INT_EXIT:0x0000002c (44)
t:0x01002710 CPU:00 USREVENT: 810 pid:100 tid:1 tag:DEADLINE_START frame:1 deadline_us:10000
"""
    parsed = parse_traceprinter(sample)
    assert parsed.header.sysname == "QNX"
    assert parsed.header.sys_release == "8.0.0"
    assert parsed.header.cpu_num == 4
    assert parsed.header.cycles_per_sec == 2_500_000_000
    assert parsed.process_names[100] == "/proc/boot/adas_aeb"
    assert len(parsed.events) == 6
    assert parsed.events[0].timestamp_us == 0.0
    assert parsed.events[1].timestamp_us == 1.0  # 2500 cycles at 2.5 GHz == 1.0 us
    assert parsed.events[3].event_class == "INT_ENTR"
    assert parsed.events[3].params["irq"] == "44"
    assert parsed.deadlines_by_thread[(100, 1)] == 10000.0


def test_parse_traceprinter_us_timestamps():
    sample = """
t:100.0us CPU:00 THREAD : THRUNNING pid:10 tid:1 priority:20 policy:RR
t:250.5us CPU:00 THREAD : THNANOSLEEP pid:10 tid:1 priority:20
"""
    parsed = parse_traceprinter(sample)
    assert len(parsed.events) == 2
    assert parsed.events[0].timestamp_us == 0.0
    assert parsed.events[1].timestamp_us == 150.5


def test_parse_traceprinter_realworld_edge_cases():
    """Verify robustness across raw QNX 8.0 traceprinter variations:
    single-colon headers, no space after colon, key=val spacing, quoted & unquoted multi-word names,
    decimal cycles, ms/ns units, P1/P2 positional thread fields, and `-p` columnar format.
    """
    sample = """
TRACE_CYCLES_PER_SEC : 2000000000
TRACE_CPU_NUM = 2
TRACE_SYS_RELEASE:: 8.0.0
TRACE_UNKNOWN_FIELD:: ignored_safely
t:0x002d4102 CPU:00 CONTROL : BUFFER sequence = 1, num_events = 250
t:2000000000 CPU:00 PROCESS :PROCCREATE_NAME ppid:1 pid:41370 name:/proc/boot/adas planner
t:2000002000 CPU:00 THREAD  :THNAMECREATE pid:41370 tid:1 name:"AEB Braking Control Loop"
t:2000004000 CPU:00 THREAD  :THRUNNING P1:41370 P2:1 prio=52 policy=SCHED_FIFO
t:2000006000 CPU:01 KER_CALL:MSG_SENDV/11 pid:41370 tid:1 coid:0x40000003
t:2000008000 CPU:01 USREVENT :800 pid:41370 tid:1 data1:42 str:"frame ok"
"""
    parsed = parse_traceprinter(sample)
    assert parsed.header.cycles_per_sec == 2_000_000_000
    assert parsed.header.cpu_num == 2
    assert parsed.process_names[41370] == "/proc/boot/adas planner"
    assert parsed.thread_names[(41370, 1)] == "AEB Braking Control Loop"

    run_evt = next(e for e in parsed.events if e.subevent == "THRUNNING")
    assert run_evt.pid == 41370
    assert run_evt.tid == 1
    assert run_evt.priority == 52
    assert run_evt.policy == "FIFO"

    ctrl_evt = next(e for e in parsed.events if e.event_class == "CONTROL")
    assert ctrl_evt.params["sequence"] == "1"
    assert ctrl_evt.params["num_events"] == "250"

    usr_evt = next(e for e in parsed.events if e.event_class == "USREVENT")
    assert usr_evt.subevent == "800"
    assert usr_evt.params["str"] == "frame ok"

    # Also verify `traceprinter -p "%C %t %Z %z"` compact columnar lines + mixed units
    custom_fmt = """
00 1.00ms THREAD THRUNNING pid:90 tid:2 priority:33 policy:2
00 1500us THREAD THNANOSLEEP pid:90 tid:2 priority:33
"""
    p2 = parse_traceprinter(custom_fmt)
    assert len(p2.events) == 2
    assert p2.events[0].timestamp_us == 0.0
    assert p2.events[1].timestamp_us == 500.0
    assert p2.events[0].policy == "RR"


def test_parse_slog2_variants():
    sample = """
Dec 21 21:12:00.029 adas_aeb.41370 events* WARNING 1 104 Priority inversion on /dev/lidar_fusion
Dec 21 21:12:00.129 adas_aeb.41370 events  CRITICAL 1 299 DEADLINE MISS on Frame 2
1734815520.500 qnx_pulse.41374 monitor 0 900 Telemetry buffer flushed
"""
    entries = parse_slog2(sample)
    assert len(entries) == 3
    assert entries[0].buffer_set == "adas_aeb"
    assert entries[0].pid == 41370
    assert entries[0].is_oldest is True
    assert entries[0].severity == "WARNING"
    assert entries[0].tid == 1
    assert entries[0].code == 104
    assert entries[1].severity == "CRITICAL"
    assert entries[2].buffer_set == "qnx_pulse"


def test_parse_buildfile_mkifs():
    sample = """
[virtual=x86_64,multiboot] boot = {
    startup-x86 -D 8250
    PATH=/proc/boot:/system/bin
    LD_LIBRARY_PATH=/proc/boot:/system/lib
    procnto-smp-instr -v
}
[+script] startup-script = {
    secpolpush -i /proc/boot/secpol.bin
    on -T slogger2_t -U 21:21 /proc/boot/slogger2 &
    waitfor /dev/slog2 4
    on -T qnxpulse_t -U 120:120 /proc/boot/qnx_pulse_agent &
    procmgr_symlink /proc/boot/ksh /bin/sh
}
[uid=0 gid=0]
{
    libc.so
    libslog2.so
    secpol.bin={./secpol.bin}
    qnx_pulse_agent
}
"""
    pb = parse_buildfile(sample)
    assert pb.arch == "x86_64"
    assert pb.boot_type == "multiboot"
    assert pb.kernel_binary == "procnto-smp-instr"
    assert pb.secpolpush_line is not None
    assert pb.has_slogger2 is True
    assert len(pb.services) == 2
    assert pb.services[1]["secpol_type"] == "qnxpulse_t"
    assert pb.services[1]["uid_gid"] == "120:120"
    assert "libslog2.so" in pb.libraries
    assert len(pb.waitfor_paths) == 1


def test_parse_secpol_rules():
    sample = """
type lidar_t;
type lidar_run_t;
on_type lidar_t run lidar_run_t;
allow lidar_t self:ability {
    nonroot
    pathspace
    public_channel
    mem_phys:0xfeb00000-0xfeb0ffff
};
allow_attach lidar_t /dev/lidar;
allow client_t lidar_t:channel connect;
"""
    ps = parse_secpol(sample)
    assert [t["name"] for t in ps.types] == ["lidar_t", "lidar_run_t"]
    assert len(ps.abilities) == 4
    assert len(ps.attach_rules) == 1
    assert ps.attach_rules[0]["path"] == "/dev/lidar"
    assert len(ps.transitions) == 1
    assert len(ps.channel_rules) == 1
