"""Authentic QNX 8.0 `traceprinter` (.kev text dump) parser.

Supports standard and real-world QNX SDP 8.0 `traceprinter` output variations including:
- Header metadata with `::`, `:`, or `=` separators (`TRACE_CYCLES_PER_SEC::`, `TRACE_CPU_NUM::`, etc.)
- Timestamps in hex cycles (`t:0x...`), decimal cycles (`t:12345`), or units (`us`, `ms`, `ns`, `s`)
- Custom `traceprinter -p "%C %t %Z %z ..."` compact columnar lines
- Varying spacing around `:` (`THREAD :THRUNNING`, `KER_CALL:MSG_SENDV/11`, `USREVENT :800`)
- Both `key:val` and `key=val` / `key = val` parameters, quoted multi-word values (`name:"Sensor Loop"`),
  and trailing multi-word `name:` / `str:` fields
- Positional `P1:` / `P2:` fallback for `pid` / `tid` on `THREAD` events
- Event classes: `PROCESS`, `THREAD`, `COMM`, `KER_CALL`, `KER_EXIT`, `INT_ENTR`, `INT_EXIT`, `INT`, `USREVENT`, `CONTROL`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from qnx_pulse.models import TraceEvent, TraceHeader

HEADER_RE = re.compile(r"^(TRACE_[A-Z0-9_]+)\s*(?:::|:|=)\s*(.*)$")

# Standard traceprinter line:
# t:0x002e1230 CPU:01 COMM    : SND_MESSAGE rcvid:0x00000001 pid:41370 tid:2
# t:125.50us   CPU:00 THREAD  :THRUNNING pid:41370 tid:1 priority:52 policy:FIFO
# t:0x1a1d6424 CPU:00 INT_ENTR:0x0000002c (44) IP:0xb8229890
# t:0x4f9a1120 CPU:01 USREVENT :800 tag:DEADLINE_START frame:1 deadline_us:10000
EVENT_LINE_RE = re.compile(
    r"^t\s*:\s*(?P<time>\S+)\s+CPU\s*:\s*(?P<cpu>\d+)\s+(?P<cls>[A-Z_]+)\s*:\s*(?P<rest>.*)$"
)

# Custom `traceprinter -p "%C %t %Z %z ..."` columnar fallback:
# 00 124.50us THREAD THRUNNING pid:41370 tid:1 priority:52
CUSTOM_FMT_RE = re.compile(
    r"^(?P<cpu>\d{1,2})\s+(?P<time>(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?(?:ns|us|ms|s)?))\s+"
    r"(?P<cls>PROCESS|THREAD|COMM|KER_CALL|KER_EXIT|INT_ENTR|INT_EXIT|INT|USREVENT|CONTROL)\s+"
    r"(?P<rest>.+)$"
)

INT_REST_RE = re.compile(
    r"^(?P<vec>0x[0-9a-fA-F]+|\d+)(?:\s*\((?P<irq>\d+)\))?(?:\s+(?P<tail>.*))?$"
)

# Matches `key:"quoted value"`, `key:val`, `key = val`, or `key=val`
KV_RE = re.compile(
    r'(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*(?::|=)\s*(?:"(?P<qval>[^"]*)"|\'(?P<sqval>[^\']*)\'|(?P<val>[^\s,]+))'
)

# Trailing multi-word unquoted `name:` or `str:` when it is the final field on a line
TRAILING_NAME_RE = re.compile(r"\b(?P<key>name|str)\s*:\s*(?P<val>[^:=]+)$")

POLICY_MAP = {
    "0": "OTHER",
    "1": "FIFO",
    "2": "RR",
    "3": "OTHER",
    "4": "SPORADIC",
    "FIFO": "FIFO",
    "SCHED_FIFO": "FIFO",
    "RR": "RR",
    "SCHED_RR": "RR",
    "SPORADIC": "SPORADIC",
    "SCHED_SPORADIC": "SPORADIC",
    "OTHER": "OTHER",
    "SCHED_OTHER": "OTHER",
}


@dataclass
class ParsedTrace:
    header: TraceHeader
    events: list[TraceEvent] = field(default_factory=list)
    process_names: dict[int, str] = field(default_factory=dict)
    thread_names: dict[tuple[int, int], str] = field(default_factory=dict)
    resmgr_paths: dict[int, list[str]] = field(default_factory=dict)
    fixed_priority_pids: set[int] = field(default_factory=set)
    deadlines_by_thread: dict[tuple[int, int], float] = field(default_factory=dict)


def _parse_raw_time_to_us(raw_time: str, cycles_per_sec: int) -> tuple[float, bool]:
    """Convert raw `t:` token to microseconds. Returns (value_us, is_cycle_based)."""
    token = raw_time.strip().rstrip(",")
    lower = token.lower()
    if lower.endswith("us"):
        return float(lower[:-2]), False
    if lower.endswith("ms"):
        return float(lower[:-2]) * 1000.0, False
    if lower.endswith("ns"):
        return float(lower[:-2]) / 1000.0, False
    if lower.endswith("s") and not lower.startswith("0x"):
        return float(lower[:-1]) * 1_000_000.0, False
    if lower.startswith("0x"):
        cycles = int(lower, 16)
        return (cycles / max(cycles_per_sec, 1)) * 1_000_000.0, True
    try:
        cycles = float(token)
        # Heuristic: large integers (>= 100000) when cycles_per_sec is set are clock cycles
        if cycles_per_sec > 0 and "." not in token and cycles >= 100_000:
            return (cycles / cycles_per_sec) * 1_000_000.0, True
        return cycles, False
    except ValueError:
        return 0.0, False


def _parse_int(val: Optional[str]) -> Optional[int]:
    if val is None:
        return None
    clean = val.strip().rstrip(",")
    try:
        return int(clean, 0)
    except ValueError:
        return None


def _extract_params(tail: str) -> dict[str, str]:
    """Extract key/value parameters supporting `:`, `=`, quoted strings, and trailing multi-word names."""
    params: dict[str, str] = {}
    if not tail:
        return params

    # Check if the final field is an unquoted multi-word `name:` or `str:`
    trailing_match = TRAILING_NAME_RE.search(tail)
    parse_span = tail
    trailing_kv: Optional[tuple[str, str]] = None
    if trailing_match:
        val_cand = trailing_match.group("val").strip()
        if " " in val_cand and not (val_cand.startswith('"') or val_cand.startswith("'")):
            trailing_kv = (trailing_match.group("key").lower(), val_cand)
            parse_span = tail[: trailing_match.start()].strip()

    for m in KV_RE.finditer(parse_span):
        key = m.group("key").lower()
        val = m.group("qval") if m.group("qval") is not None else (
            m.group("sqval") if m.group("sqval") is not None else m.group("val")
        )
        if val is not None:
            params[key] = val.strip()

    if trailing_kv is not None:
        params[trailing_kv[0]] = trailing_kv[1]

    return params


def parse_traceprinter(text: str) -> ParsedTrace:
    """Parse QNX 8.0 `traceprinter` text output into structured events and metadata."""
    header = TraceHeader()
    raw_events: list[tuple[float, bool, TraceEvent]] = []
    process_names: dict[int, str] = {1: "procnto-smp-instr"}
    thread_names: dict[tuple[int, int], str] = {}
    resmgr_paths: dict[int, list[str]] = {}
    fixed_priority_pids: set[int] = set()
    deadlines_by_thread: dict[tuple[int, int], float] = {}

    seq = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("#")
            or line.startswith("--")
            or line.startswith("TRACEPRINTER")
            or line.startswith("TRACEPARSER")
        ):
            continue

        hm = HEADER_RE.match(line)
        if hm:
            key, val = hm.group(1), hm.group(2).strip()
            if key == "TRACE_FILE_NAME":
                header.file_name = val
            elif key == "TRACE_SYSNAME":
                header.sysname = val
            elif key == "TRACE_SYS_RELEASE":
                header.sys_release = val
            elif key == "TRACE_MACHINE":
                header.machine = val
            elif key == "TRACE_NODENAME":
                header.nodename = val
            elif key == "TRACE_CPU_NUM":
                parsed_cpu = _parse_int(val)
                if parsed_cpu and parsed_cpu > 0:
                    header.cpu_num = parsed_cpu
            elif key == "TRACE_CYCLES_PER_SEC":
                parsed_cps = _parse_int(val.split()[0] if val else None)
                if parsed_cps and parsed_cps > 0:
                    header.cycles_per_sec = parsed_cps
            elif key == "TRACE_BOOT_DATE":
                header.boot_date = val
            elif key == "TRACE_DATE":
                header.trace_date = val
            elif key == "TRACE_TRACELOGGER_ARGS":
                header.tracelogger_args = val
            continue

        em = EVENT_LINE_RE.match(line)
        if not em:
            em = CUSTOM_FMT_RE.match(line)
        if not em:
            continue

        raw_time = em.group("time")
        cpu = int(em.group("cpu"))
        event_class = em.group("cls").upper()
        rest = em.group("rest").strip()
        ts_us, is_cycle = _parse_raw_time_to_us(raw_time, header.cycles_per_sec)

        subevent = ""
        params: dict[str, str] = {}

        if event_class in ("INT_ENTR", "INT_EXIT"):
            subevent = event_class
            im = INT_REST_RE.match(rest)
            if im:
                params["vector"] = im.group("vec")
                if im.group("irq"):
                    params["irq"] = im.group("irq")
                else:
                    try:
                        params["irq"] = str(int(im.group("vec"), 0))
                    except ValueError:
                        params["irq"] = im.group("vec")
                params.update(_extract_params(im.group("tail") or ""))
            else:
                params.update(_extract_params(rest))
        else:
            # Handle optional leading colon (e.g., `THREAD :THRUNNING` where rest is `THRUNNING ...`)
            rest_clean = rest.lstrip(":").strip()
            parts = rest_clean.split(None, 1)
            subevent = parts[0].rstrip(":") if parts else ""
            tail = parts[1] if len(parts) > 1 else ""
            params = _extract_params(tail)

        pid = _parse_int(params.get("pid"))
        tid = _parse_int(params.get("tid"))
        # Positional P1/P2 fallback for raw QNX traceprinter THREAD dumps
        if event_class == "THREAD":
            if pid is None and "p1" in params:
                pid = _parse_int(params.get("p1"))
            if tid is None and "p2" in params:
                tid = _parse_int(params.get("p2"))

        priority = _parse_int(params.get("priority") or params.get("prio"))
        policy_raw = params.get("policy")
        policy = POLICY_MAP.get(policy_raw.upper(), policy_raw) if policy_raw else None

        # Populate process/thread/resource-manager metadata tables
        if pid is not None and "proc" in params and pid not in process_names:
            process_names[pid] = params["proc"]
        if params.get("fixed_prio") == "1":
            fp_target = _parse_int(params.get("target_pid") or params.get("server_pid")) or pid
            if fp_target is not None:
                fixed_priority_pids.add(fp_target)

        if event_class == "PROCESS" and subevent in ("PROCCREATE_NAME", "PROCCREATE"):
            if pid is not None and "name" in params:
                process_names[pid] = params["name"]
        elif event_class == "THREAD" and subevent in ("THNAME", "THNAMECREATE"):
            if pid is not None and tid is not None and "name" in params:
                thread_names[(pid, tid)] = params["name"]
        elif event_class == "USREVENT":
            if "resmgr_path" in params and pid is not None:
                resmgr_paths.setdefault(pid, [])
                if params["resmgr_path"] not in resmgr_paths[pid]:
                    resmgr_paths[pid].append(params["resmgr_path"])
            if params.get("chflags") == "_NTO_CHF_FIXED_PRIORITY" and pid is not None:
                fixed_priority_pids.add(pid)
            if "deadline_us" in params and pid is not None and tid is not None:
                try:
                    deadlines_by_thread[(pid, tid)] = float(params["deadline_us"])
                except ValueError:
                    pass
        elif event_class == "KER_CALL" and subevent.startswith("CHANNEL_CREATE"):
            flags_val = _parse_int(params.get("flags"))
            if pid is not None and (
                params.get("flags_name") == "_NTO_CHF_FIXED_PRIORITY"
                or (flags_val is not None and (flags_val & 0x0001))
            ):
                fixed_priority_pids.add(pid)

        seq += 1
        evt = TraceEvent(
            seq=seq,
            timestamp_us=ts_us,
            raw_time=raw_time,
            cpu=cpu,
            event_class=event_class,
            subevent=subevent,
            pid=pid,
            tid=tid,
            priority=priority,
            policy=policy,
            params=params,
            raw_line=line,
        )
        raw_events.append((ts_us, is_cycle, evt))

    # Normalize timestamps relative to first event so timelines start cleanly at 0.0 us
    if raw_events:
        min_ts = min(t for t, _, _ in raw_events)
        max_cpu = max(e.cpu for _, _, e in raw_events)
        if max_cpu + 1 > header.cpu_num:
            header.cpu_num = max_cpu + 1
        events: list[TraceEvent] = []
        for ts_us, _, evt in raw_events:
            evt.timestamp_us = round(ts_us - min_ts, 3)
            events.append(evt)
        events.sort(key=lambda e: (e.timestamp_us, e.seq))
    else:
        events = []

    return ParsedTrace(
        header=header,
        events=events,
        process_names=process_names,
        thread_names=thread_names,
        resmgr_paths=resmgr_paths,
        fixed_priority_pids=fixed_priority_pids,
        deadlines_by_thread=deadlines_by_thread,
    )
