"""QNX 8.0 Real-Time Microkernel Trace Analyzer.

Computes per-thread WCET / p50 / p95 / p99 / jitter, per-core CPU & IRQ utilization,
priority inversion incidents across synchronous MsgSend/MsgReply IPC chains,
IRQ storm incidents, deadline miss root-cause correlation, and latency histograms.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Optional

from qnx_pulse.models import (
    CoreUtilization,
    DeadlineMissIncident,
    IrqStormIncident,
    PriorityInversionIncident,
    Slog2Entry,
    ThreadMetrics,
    ThreadSegment,
    TraceAnalysisResult,
)
from qnx_pulse.parsers.slog2 import parse_slog2
from qnx_pulse.parsers.traceprinter import ParsedTrace, parse_traceprinter
from qnx_pulse.analyzers.ipc_topology import build_ipc_topology


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    idx = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return round(ordered[lo], 2)
    frac = idx - lo
    return round(ordered[lo] * (1.0 - frac) + ordered[hi] * frac, 2)


def _short_proc_name(full_path: str) -> str:
    return full_path.rstrip("/").split("/")[-1] if full_path else "unknown"


def _thread_label(parsed: ParsedTrace, pid: int, tid: int) -> str:
    tname = parsed.thread_names.get((pid, tid))
    pname = _short_proc_name(parsed.process_names.get(pid, f"pid_{pid}"))
    if tname:
        return f"{pname}/{tname} ({pid}:{tid})"
    return f"{pname} ({pid}:{tid})"


def _build_latency_histogram(latencies_us: list[float]) -> list[dict[str, Any]]:
    buckets = [
        ("0-100 us", 0.0, 100.0),
        ("100-250 us", 100.0, 250.0),
        ("250-500 us", 250.0, 500.0),
        ("0.5-1 ms", 500.0, 1000.0),
        ("1-2.5 ms", 1000.0, 2500.0),
        ("2.5-5 ms", 2500.0, 5000.0),
        ("5-10 ms", 5000.0, 10000.0),
        (">10 ms", 10000.0, float("inf")),
    ]
    counts = [0] * len(buckets)
    for lat in latencies_us:
        for idx, (_, lo, hi) in enumerate(buckets):
            if lo <= lat < hi:
                counts[idx] += 1
                break
    return [
        {"bucket": label, "count": counts[idx], "lo_us": lo, "hi_us": None if math.isinf(hi) else hi}
        for idx, (label, lo, hi) in enumerate(buckets)
    ]


def analyze_trace(
    trace_text: str,
    slog2_text: str = "",
    scenario_id: str = "custom",
    scenario_name: str = "QNX 8.0 Kernel Trace",
    description: str = "",
) -> TraceAnalysisResult:
    """Analyze a QNX 8.0 `traceprinter` dump and optional `slog2info` log."""
    parsed = parse_traceprinter(trace_text)
    slog2_entries: list[Slog2Entry] = parse_slog2(slog2_text) if slog2_text.strip() else []
    events = parsed.events

    if not events:
        return TraceAnalysisResult(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=description,
            header=parsed.header,
            correlated_logs=slog2_entries,
        )

    total_duration_us = max(events[-1].timestamp_us - events[0].timestamp_us, 1.0)
    num_cpus = max(parsed.header.cpu_num, 1)

    # State tracking structures
    # Per-thread state: (state, start_us, cpu, priority)
    thread_state: dict[tuple[int, int], tuple[str, float, int, int]] = {}
    thread_prio: dict[tuple[int, int], int] = {}
    thread_prios_seen: dict[tuple[int, int], list[int]] = defaultdict(list)
    thread_policy: dict[tuple[int, int], str] = {}
    thread_run_durations: dict[tuple[int, int], list[float]] = defaultdict(list)
    thread_ready_waits: dict[tuple[int, int], list[float]] = defaultdict(list)
    thread_ipc_blocked: dict[tuple[int, int], float] = defaultdict(float)
    thread_preemptions: dict[tuple[int, int], int] = defaultdict(int)
    thread_seen: set[tuple[int, int]] = set()

    # Running thread on each CPU: cpu -> (pid, tid, prio)
    cpu_running: dict[int, Optional[tuple[int, int, int]]] = {c: None for c in range(num_cpus)}
    cpu_busy_us: dict[int, float] = defaultdict(float)
    cpu_irq_us: dict[int, float] = defaultdict(float)
    cpu_ctx_switches: dict[int, int] = defaultdict(int)

    timeline_segments: list[ThreadSegment] = []

    # IRQ tracking: (cpu, irq) -> (start_us, vector, preempted_thread_label)
    active_irqs: dict[tuple[int, str], tuple[float, str, Optional[str]]] = {}
    irq_events: list[dict[str, Any]] = []
    irq_by_key: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)

    # IPC transaction tracking keyed by rcvid:
    # rcvid -> dict with client_pid, client_tid, client_prio, server_pid, server_tid, server_prio,
    # send_us, rec_us, reply_us, inherited, preemptors
    active_ipc: dict[str, dict[str, Any]] = {}
    completed_ipc: list[dict[str, Any]] = []
    pulse_events: list[dict[str, Any]] = []
    # Track recent async pulse handoffs from server -> worker
    recent_pulse_targets: dict[int, list[dict[str, Any]]] = defaultdict(list)

    # Deadline frame tracking: (pid, tid, frame) -> (start_us, deadline_us)
    active_frames: dict[tuple[int, int, str], tuple[float, float]] = {}
    completed_frames: list[dict[str, Any]] = []

    def close_thread_segment(key: tuple[int, int], end_us: float) -> None:
        if key not in thread_state:
            return
        st, start_us, cpu, prio = thread_state[key]
        dur = max(0.0, end_us - start_us)
        if dur > 0.0:
            pid, tid = key
            pname = _short_proc_name(parsed.process_names.get(pid, f"pid_{pid}"))
            timeline_segments.append(
                ThreadSegment(
                    pid=pid,
                    tid=tid,
                    process_name=pname,
                    thread_label=_thread_label(parsed, pid, tid),
                    cpu=cpu,
                    state=st,
                    start_us=round(start_us, 2),
                    end_us=round(end_us, 2),
                    duration_us=round(dur, 2),
                    priority=prio,
                )
            )
            if st == "RUNNING":
                thread_run_durations[key].append(dur)
                cpu_busy_us[cpu] += dur
            elif st == "READY":
                thread_ready_waits[key].append(dur)
            elif st in ("SEND", "REPLY", "MUTEX", "CONDVAR"):
                thread_ipc_blocked[key] += dur

    def set_thread_state(key: tuple[int, int], new_state: str, ts_us: float, cpu: int, prio: Optional[int]) -> None:
        thread_seen.add(key)
        resolved_prio = prio if prio is not None else thread_prio.get(key, 10)
        thread_prio[key] = resolved_prio
        thread_prios_seen[key].append(resolved_prio)
        close_thread_segment(key, ts_us)
        thread_state[key] = (new_state, ts_us, cpu, resolved_prio)

    # Main chronological walk
    for evt in events:
        ts = evt.timestamp_us
        cpu = evt.cpu
        cls = evt.event_class
        sub = evt.subevent

        if cls == "THREAD" and evt.pid is not None and evt.tid is not None:
            key = (evt.pid, evt.tid)
            thread_seen.add(key)
            if evt.policy:
                thread_policy[key] = evt.policy
            if evt.priority is not None:
                thread_prio[key] = evt.priority
                thread_prios_seen[key].append(evt.priority)

            if sub == "THRUNNING":
                prev = cpu_running.get(cpu)
                cur_prio = thread_prio.get(key, 10)
                if prev is not None and (prev[0], prev[1]) != key:
                    prev_key = (prev[0], prev[1])
                    prev_st = thread_state.get(prev_key)
                    if prev_st and prev_st[0] == "RUNNING":
                        # Preempted directly by another thread
                        set_thread_state(prev_key, "READY", ts, cpu, prev[2])
                        thread_preemptions[prev_key] += 1
                    cpu_ctx_switches[cpu] += 1
                elif prev is None:
                    cpu_ctx_switches[cpu] += 1

                set_thread_state(key, "RUNNING", ts, cpu, cur_prio)
                cpu_running[cpu] = (evt.pid, evt.tid, cur_prio)

                # Check if this running thread is preempting a server currently handling
                # an active high-priority IPC request (Priority Inversion signature!)
                for rcvid, tx in active_ipc.items():
                    srv_key = (tx["server_pid"], tx["server_tid"])
                    cli_key = (tx["client_pid"], tx["client_tid"])
                    if key == srv_key:
                        # Update effective server priority observed during service
                        tx["observed_server_prios"].append(cur_prio)
                        if cur_prio >= tx["client_prio"]:
                            tx["priority_inherited"] = True
                    elif key != cli_key:
                        srv_prio = tx["server_prio"]
                        cli_prio = tx["client_prio"]
                        # Medium-priority thread running while high-priority client waits on lower-priority server
                        if srv_prio < cur_prio < cli_prio:
                            srv_state_entry = thread_state.get(srv_key)
                            srv_is_delayed = (
                                srv_state_entry is not None
                                and srv_state_entry[0] in ("READY", "RUNNING", "MUTEX")
                                and not tx["priority_inherited"]
                            )
                            if srv_is_delayed or (tx["server_pid"] in parsed.fixed_priority_pids):
                                tx["preemptors"].append({
                                    "thread": _thread_label(parsed, evt.pid, evt.tid),
                                    "pid": evt.pid,
                                    "tid": evt.tid,
                                    "prio": cur_prio,
                                    "start_us": ts,
                                    "cpu": cpu,
                                })

            elif sub == "THREADY":
                cur_prio = thread_prio.get(key, 10)
                prev = cpu_running.get(cpu)
                if prev is not None and (prev[0], prev[1]) == key:
                    cpu_running[cpu] = None
                    thread_preemptions[key] += 1
                set_thread_state(key, "READY", ts, cpu, cur_prio)

            elif sub in ("THSEND", "THRECEIVE", "THREPLY", "THMUTEX", "THCONDVAR", "THNANOSLEEP"):
                state_name = sub[2:]  # strip "TH"
                cur_prio = thread_prio.get(key, 10)
                prev = cpu_running.get(cpu)
                if prev is not None and (prev[0], prev[1]) == key:
                    cpu_running[cpu] = None
                set_thread_state(key, state_name, ts, cpu, cur_prio)

            elif sub == "THCREATE":
                thread_prio.setdefault(key, evt.priority if evt.priority is not None else 10)
                thread_policy.setdefault(key, evt.policy or "FIFO")

        elif cls == "COMM":
            rcvid = evt.params.get("rcvid")
            if sub == "SND_MESSAGE":
                # Client sends synchronous message to server.
                # Support both explicit src_pid/src_tid + dst_pid/dst_tid AND standard traceprinter
                # where current running thread on CPU is sender and pid/tid is destination server.
                running = cpu_running.get(cpu)
                if "target_pid" in evt.params:
                    src_pid = evt.pid if evt.pid is not None else (running[0] if running else None)
                    src_tid = evt.tid if evt.tid is not None else (running[1] if running else 1)
                    dst_pid = int(evt.params["target_pid"], 0)
                    dst_tid = int(evt.params.get("target_tid", "1"), 0)
                else:
                    src_pid = int(evt.params["src_pid"], 0) if "src_pid" in evt.params else (running[0] if running else evt.pid)
                    src_tid = int(evt.params["src_tid"], 0) if "src_tid" in evt.params else (running[1] if running else evt.tid)
                    dst_pid = int(evt.params["dst_pid"], 0) if "dst_pid" in evt.params else evt.pid
                    dst_tid = int(evt.params["dst_tid"], 0) if "dst_tid" in evt.params else evt.tid

                if src_pid is not None and dst_pid is not None:
                    src_tid_v = src_tid or 1
                    dst_tid_v = dst_tid or 1
                    cli_prio = thread_prio.get((src_pid, src_tid_v), evt.priority or 10)
                    peer_prio_param = int(evt.params["peer_prio"], 0) if "peer_prio" in evt.params else None
                    srv_prio = peer_prio_param if peer_prio_param is not None else thread_prio.get((dst_pid, dst_tid_v), 10)
                    tx_id = rcvid or f"msg_{evt.seq}"
                    fixed_flag = (
                        (dst_pid in parsed.fixed_priority_pids)
                        or (evt.params.get("chflags") == "_NTO_CHF_FIXED_PRIORITY")
                        or (evt.params.get("fixed_prio") == "1")
                    )
                    active_ipc[tx_id] = {
                        "rcvid": tx_id,
                        "client_pid": src_pid,
                        "client_tid": src_tid_v,
                        "client_prio": cli_prio,
                        "server_pid": dst_pid,
                        "server_tid": dst_tid_v,
                        "server_prio": srv_prio,
                        "send_us": ts,
                        "rec_us": None,
                        "reply_us": None,
                        "fixed_priority_flag": fixed_flag,
                        "priority_inherited": not fixed_flag and (srv_prio >= cli_prio),
                        "observed_server_prios": [],
                        "preemptors": [],
                    }
                    # Mark client as REPLY-blocked until reply arrives
                    set_thread_state((src_pid, src_tid_v), "REPLY", ts, cpu, cli_prio)
                    if running and (running[0], running[1]) == (src_pid, src_tid_v):
                        cpu_running[cpu] = None

            elif sub == "REC_MESSAGE":
                if rcvid and rcvid in active_ipc:
                    tx = active_ipc[rcvid]
                    tx["rec_us"] = ts
                    if "dst_pid" in evt.params:
                        tx["server_pid"] = int(evt.params["dst_pid"], 0)
                    elif evt.pid is not None and "client_pid" in evt.params:
                        tx["server_pid"] = evt.pid
                    if "dst_tid" in evt.params:
                        tx["server_tid"] = int(evt.params["dst_tid"], 0)
                    elif evt.tid is not None and evt.pid == tx["server_pid"]:
                        tx["server_tid"] = evt.tid
                    srv_key = (tx["server_pid"], tx["server_tid"])
                    # Check if server priority boosted on MsgReceive
                    if evt.priority is not None:
                        thread_prio[srv_key] = evt.priority
                        tx["observed_server_prios"].append(evt.priority)
                        if evt.priority >= tx["client_prio"]:
                            tx["priority_inherited"] = True
                        else:
                            tx["priority_inherited"] = False
                            tx["server_prio"] = evt.priority
                    else:
                        srv_p = thread_prio.get(srv_key, tx["server_prio"])
                        if not tx["fixed_priority_flag"] and srv_p < tx["client_prio"]:
                            # Unless explicitly fixed-priority or shown lower in next THRUNNING, assume pending check
                            pass

            elif sub == "REPLY_MESSAGE":
                if rcvid and rcvid in active_ipc:
                    tx = active_ipc.pop(rcvid)
                    tx["reply_us"] = ts
                    tx["latency_us"] = round(max(0.0, ts - tx["send_us"]), 2)
                    # Determine whether priority inheritance actually occurred
                    if tx["observed_server_prios"]:
                        max_obs = max(tx["observed_server_prios"])
                        tx["priority_inherited"] = max_obs >= tx["client_prio"]
                        if not tx["priority_inherited"]:
                            tx["server_prio"] = min(tx["observed_server_prios"])
                    elif tx["fixed_priority_flag"]:
                        tx["priority_inherited"] = False
                    else:
                        tx["priority_inherited"] = True
                    completed_ipc.append(tx)
                    # Unblock client to READY
                    cli_key = (tx["client_pid"], tx["client_tid"])
                    set_thread_state(cli_key, "READY", ts, cpu, tx["client_prio"])

            elif sub in ("SND_PULSE", "SND_PULSE_EXE"):
                running = cpu_running.get(cpu)
                src_pid = int(evt.params["src_pid"], 0) if "src_pid" in evt.params else (running[0] if running else 1)
                dst_pid = int(evt.params["dst_pid"], 0) if "dst_pid" in evt.params else (evt.pid or 1)
                pe = {
                    "src_pid": src_pid,
                    "dst_pid": dst_pid,
                    "ts_us": ts,
                    "code": evt.params.get("code", "0"),
                }
                pulse_events.append(pe)
                recent_pulse_targets[src_pid].append(pe)

        elif cls == "INT_ENTR" or (cls == "INT" and sub == "INT_ENTR"):
            irq = evt.params.get("irq", evt.params.get("vector", "0"))
            vec = evt.params.get("vector", irq)
            prev = cpu_running.get(cpu)
            preempted_lbl = _thread_label(parsed, prev[0], prev[1]) if prev else None
            active_irqs[(cpu, irq)] = (ts, vec, preempted_lbl)

        elif cls == "INT_EXIT" or (cls == "INT" and sub == "INT_EXIT"):
            irq = evt.params.get("irq", evt.params.get("vector", "0"))
            if (cpu, irq) in active_irqs:
                start_us, vec, preempted_lbl = active_irqs.pop((cpu, irq))
                dur = max(0.5, round(ts - start_us, 2))
                cpu_irq_us[cpu] += dur
                rec = {
                    "cpu": cpu,
                    "irq": irq,
                    "vector": vec,
                    "start_us": round(start_us, 2),
                    "end_us": round(ts, 2),
                    "duration_us": dur,
                    "preempted_thread": preempted_lbl,
                }
                irq_events.append(rec)
                irq_by_key[(cpu, irq)].append(rec)

        elif cls == "USREVENT":
            tag = evt.params.get("tag", "").upper()
            if tag == "DEADLINE_START" and evt.pid is not None and evt.tid is not None:
                frame = evt.params.get("frame", str(evt.seq))
                dl = float(evt.params.get("deadline_us", parsed.deadlines_by_thread.get((evt.pid, evt.tid), 10000.0)))
                active_frames[(evt.pid, evt.tid, frame)] = (ts, dl)
            elif tag == "DEADLINE_END" and evt.pid is not None and evt.tid is not None:
                frame = evt.params.get("frame", "")
                fkey = (evt.pid, evt.tid, frame)
                if fkey in active_frames:
                    start_us, dl = active_frames.pop(fkey)
                    actual = round(ts - start_us, 2)
                    completed_frames.append({
                        "pid": evt.pid,
                        "tid": evt.tid,
                        "frame": frame,
                        "start_us": start_us,
                        "end_us": ts,
                        "deadline_us": dl,
                        "actual_us": actual,
                    })

    # Close remaining open thread segments at trace end
    end_ts = events[-1].timestamp_us
    for key in list(thread_state.keys()):
        close_thread_segment(key, end_ts)

    # Close any still-open IPC transactions as truncated
    for tx in active_ipc.values():
        tx["reply_us"] = end_ts
        tx["latency_us"] = round(max(0.0, end_ts - tx["send_us"]), 2)
        completed_ipc.append(tx)

    # 1. Detect Priority Inversion Incidents
    priority_inversions: list[PriorityInversionIncident] = []
    inversion_rcvid_set: set[str] = set()
    inv_idx = 0
    for tx in completed_ipc:
        if not tx["priority_inherited"] and tx["client_prio"] > tx["server_prio"]:
            has_preemptor = len(tx["preemptors"]) > 0
            # Even if no explicit medium preemptor logged, if fixed priority caused high latency (>1000us), still flag!
            if has_preemptor or (tx["fixed_priority_flag"] and tx["latency_us"] > 1000.0):
                inv_idx += 1
                inversion_rcvid_set.add(tx["rcvid"])
                preemptor = (
                    max(tx["preemptors"], key=lambda p: p["prio"])
                    if has_preemptor
                    else {"thread": "unboosted ready-queue contention", "prio": tx["server_prio"] + 1}
                )
                cli_lbl = _thread_label(parsed, tx["client_pid"], tx["client_tid"])
                srv_lbl = _thread_label(parsed, tx["server_pid"], tx["server_tid"])
                srv_proc = _short_proc_name(parsed.process_names.get(tx["server_pid"], f"pid_{tx['server_pid']}"))
                res_paths = parsed.resmgr_paths.get(tx["server_pid"], [])
                res_hint = f" ({', '.join(res_paths)})" if res_paths else ""

                if tx["fixed_priority_flag"] or (tx["server_pid"] in parsed.fixed_priority_pids):
                    mechanism = (
                        f"Channel created with _NTO_CHF_FIXED_PRIORITY on {srv_proc}{res_hint}, "
                        f"disabling QNX 8.0 native MsgSend/MsgReply priority inheritance."
                    )
                else:
                    mechanism = (
                        f"Server thread {srv_lbl} ran at priority {tx['server_prio']} without inheriting "
                        f"client priority {tx['client_prio']} during synchronous IPC ({tx['rcvid']})."
                    )

                remediation_c = (
                    f"// In {srv_proc} (QNX 8.0 Resource Manager / IPC Server):\n"
                    f"// REMOVE _NTO_CHF_FIXED_PRIORITY so MsgReceive() inherits client priority ({tx['client_prio']})\n"
                    f"- int chid = ChannelCreate(_NTO_CHF_FIXED_PRIORITY);\n"
                    f"+ int chid = ChannelCreate(0); // Enables QNX 8.0 kernel priority inheritance\n"
                    f"// If using dispatch_create_channel(), omit _NTO_CHF_FIXED_PRIORITY from flags.\n"
                    f"// If protecting shared state with a mutex, set PTHREAD_PRIO_INHERIT via pthread_mutexattr_setprotocol()."
                )

                severity = "CRITICAL" if tx["latency_us"] >= 3000.0 or (tx["client_prio"] - tx["server_prio"] >= 20) else "HIGH"
                priority_inversions.append(
                    PriorityInversionIncident(
                        id=f"PI-{inv_idx:03d}",
                        severity=severity,
                        start_us=round(tx["send_us"], 2),
                        end_us=round(tx["reply_us"], 2),
                        duration_us=tx["latency_us"],
                        high_prio_client=cli_lbl,
                        high_prio=tx["client_prio"],
                        blocked_server=srv_lbl,
                        server_prio=tx["server_prio"],
                        preempting_thread=preemptor["thread"],
                        preempting_prio=preemptor["prio"],
                        rcvid=tx["rcvid"],
                        mechanism=mechanism,
                        explanation=(
                            f"High-priority client {cli_lbl} [prio {tx['client_prio']}] blocked in THREPLY on "
                            f"{srv_lbl} [prio {tx['server_prio']}] for {tx['latency_us']:.1f} us ({tx['latency_us']/1000:.2f} ms). "
                            f"Because server priority stayed at {tx['server_prio']}, medium-priority {preemptor['thread']} "
                            f"[prio {preemptor['prio']}] preempted the server and caused unbounded priority inversion."
                        ),
                        remediation_c=remediation_c,
                    )
                )

    # 2. Detect IRQ Storm Incidents
    irq_storms: list[IrqStormIncident] = []
    storm_idx = 0
    for (cpu, irq), recs in sorted(irq_by_key.items()):
        if len(recs) < 5:
            continue
        start_u = recs[0]["start_us"]
        end_u = recs[-1]["end_us"]
        window_us = max(end_u - start_u, 1.0)
        rate_hz = (len(recs) / window_us) * 1_000_000.0
        total_irq_time = sum(r["duration_us"] for r in recs)
        share_pct = (total_irq_time / total_duration_us) * 100.0
        if rate_hz >= 2500.0 or share_pct >= 15.0:
            storm_idx += 1
            impacted = sorted({r["preempted_thread"] for r in recs if r.get("preempted_thread")})
            irq_storms.append(
                IrqStormIncident(
                    id=f"IRQ-{storm_idx:03d}",
                    severity="CRITICAL" if share_pct >= 25.0 or rate_hz >= 8000.0 else "HIGH",
                    irq_vector=f"IRQ {irq} ({recs[0]['vector']})",
                    cpu=cpu,
                    start_us=round(start_u, 2),
                    end_us=round(end_u, 2),
                    count=len(recs),
                    rate_hz=round(rate_hz, 1),
                    total_cpu_time_us=round(total_irq_time, 2),
                    cpu_share_pct=round(share_pct, 2),
                    impacted_threads=impacted,
                    explanation=(
                        f"IRQ {irq} fired {len(recs)} times on CPU:{cpu:02d} within {window_us/1000:.2f} ms "
                        f"({rate_hz:,.0f} Hz), consuming {share_pct:.1f}% of core capacity and repeatedly "
                        f"preempting real-time threads ({', '.join(impacted) or 'active RT loop'})."
                    ),
                    remediation=(
                        f"1. Replace raw InterruptAttach() ISR work with InterruptAttachEvent() + a bounded-priority IST thread.\n"
                        f"2. Pin IRQ {irq} handler away from real-time control CPU:{cpu:02d} via ThreadCtl(_NTO_TCTL_RUNMASK, ...) "
                        f"and startup APIC/GIC affinity routing.\n"
                        f"3. Enable hardware interrupt coalescing / DMA ring batching on the peripheral controller."
                    ),
                )
            )

    # 3. Detect Deadline Misses and link to Root Causes
    deadline_misses: list[DeadlineMissIncident] = []
    misses_by_thread: dict[tuple[int, int], int] = defaultdict(int)
    dm_idx = 0
    for fr in completed_frames:
        if fr["actual_us"] > fr["deadline_us"]:
            dm_idx += 1
            key = (fr["pid"], fr["tid"])
            misses_by_thread[key] += 1
            lbl = _thread_label(parsed, fr["pid"], fr["tid"])
            linked: list[str] = []
            causes: list[str] = []

            for pi in priority_inversions:
                if pi.start_us <= fr["end_us"] and pi.end_us >= fr["start_us"]:
                    linked.append(pi.id)
                    causes.append(
                        f"Priority inversion {pi.id} ({pi.duration_us/1000:.2f} ms blocked on {pi.blocked_server} while preempted by {pi.preempting_thread})"
                    )
            for st in irq_storms:
                if st.start_us <= fr["end_us"] and st.end_us >= fr["start_us"]:
                    linked.append(st.id)
                    causes.append(
                        f"IRQ storm {st.id} ({st.irq_vector} on CPU:{st.cpu:02d} at {st.rate_hz:,.0f} Hz consuming {st.cpu_share_pct:.1f}% CPU)"
                    )

            root_cause = "; ".join(causes) if causes else (
                f"Execution & scheduling latency ({fr['actual_us']/1000:.2f} ms) exceeded budget ({fr['deadline_us']/1000:.2f} ms)."
            )
            deadline_misses.append(
                DeadlineMissIncident(
                    id=f"DM-{dm_idx:03d}",
                    thread_label=lbl,
                    pid=fr["pid"],
                    tid=fr["tid"],
                    frame_id=fr["frame"],
                    deadline_us=round(fr["deadline_us"], 2),
                    actual_us=round(fr["actual_us"], 2),
                    overrun_us=round(fr["actual_us"] - fr["deadline_us"], 2),
                    timestamp_us=round(fr["end_us"], 2),
                    root_cause=root_cause,
                    linked_incident_ids=linked,
                )
            )

    # 4. Build Per-Core Utilization
    cores: list[CoreUtilization] = []
    for c in range(num_cpus):
        irq_u = min(cpu_irq_us.get(c, 0.0), total_duration_us)
        busy_u = min(cpu_busy_us.get(c, 0.0), total_duration_us)
        total_active = min(busy_u + irq_u, total_duration_us)
        idle_u = max(0.0, total_duration_us - total_active)
        cores.append(
            CoreUtilization(
                cpu=c,
                busy_us=round(busy_u, 2),
                irq_us=round(irq_u, 2),
                idle_us=round(idle_u, 2),
                utilization_pct=round((total_active / total_duration_us) * 100.0, 2),
                irq_pct=round((irq_u / total_duration_us) * 100.0, 2),
                context_switches=cpu_ctx_switches.get(c, 0),
            )
        )

    # 5. Build Per-Thread Real-Time Metrics
    frame_latencies_by_thread: dict[tuple[int, int], list[float]] = defaultdict(list)
    for fr in completed_frames:
        frame_latencies_by_thread[(fr["pid"], fr["tid"])].append(fr["actual_us"])

    threads: list[ThreadMetrics] = []
    for key in sorted(thread_seen):
        pid, tid = key
        runs = thread_run_durations.get(key, [])
        frame_lats = frame_latencies_by_thread.get(key, [])
        samples = frame_lats if frame_lats else runs
        total_run = sum(runs)
        prios = thread_prios_seen.get(key, [thread_prio.get(key, 10)])
        ready_waits = thread_ready_waits.get(key, [])
        jitter = round(max(samples) - min(samples), 2) if len(samples) >= 2 else (round(max(ready_waits), 2) if ready_waits else 0.0)

        threads.append(
            ThreadMetrics(
                key=f"{pid}:{tid}",
                pid=pid,
                tid=tid,
                process_name=_short_proc_name(parsed.process_names.get(pid, f"pid_{pid}")),
                thread_label=_thread_label(parsed, pid, tid),
                base_priority=prios[0] if prios else 10,
                min_priority=min(prios) if prios else 10,
                max_priority=max(prios) if prios else 10,
                policy=thread_policy.get(key, "FIFO"),
                activations=len(frame_lats) if frame_lats else len(runs),
                total_run_us=round(total_run, 2),
                cpu_share_pct=round((total_run / (total_duration_us * num_cpus)) * 100.0, 2),
                wcet_us=round(max(samples), 2) if samples else 0.0,
                avg_exec_us=round(sum(samples) / len(samples), 2) if samples else 0.0,
                p50_us=_percentile(samples, 50.0),
                p95_us=_percentile(samples, 95.0),
                p99_us=_percentile(samples, 99.0),
                max_ready_wait_us=round(max(ready_waits), 2) if ready_waits else 0.0,
                jitter_us=jitter,
                ipc_blocked_us=round(thread_ipc_blocked.get(key, 0.0), 2),
                deadline_us=parsed.deadlines_by_thread.get(key),
                deadline_misses=misses_by_thread.get(key, 0),
                preemptions=thread_preemptions.get(key, 0),
            )
        )

    threads.sort(key=lambda t: (-t.deadline_misses, -t.max_priority, -t.wcet_us))

    # 6. Build IPC Topology
    ipc_topology = build_ipc_topology(
        parsed=parsed,
        completed_ipc=completed_ipc,
        pulse_events=pulse_events,
        inversion_rcvid_set=inversion_rcvid_set,
        threads=threads,
    )

    # 7. Latency Histogram (use IPC round-trip latencies + frame response latencies if no IPC)
    ipc_latencies = [tx["latency_us"] for tx in completed_ipc]
    if not ipc_latencies:
        ipc_latencies = [fr["actual_us"] for fr in completed_frames]
    latency_histogram = _build_latency_histogram(ipc_latencies)

    # 8. Compute Overall Real-Time Health Score
    score = 100
    score -= min(45, len(priority_inversions) * 28)
    score -= min(40, len(irq_storms) * 25)
    score -= min(35, len(deadline_misses) * 18)
    critical_logs = sum(1 for l in slog2_entries if l.severity in ("CRITICAL", "ERROR"))
    score -= min(15, critical_logs * 4)
    health_score = max(0, min(100, score))

    if health_score >= 85 and not priority_inversions and not irq_storms and not deadline_misses:
        health_status = "HEALTHY"
    elif health_score >= 55:
        health_status = "DEGRADED"
    else:
        health_status = "CRITICAL"

    return TraceAnalysisResult(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        description=description,
        header=parsed.header,
        duration_us=round(total_duration_us, 2),
        total_events=len(events),
        slog2_count=len(slog2_entries),
        health_score=health_score,
        health_status=health_status,
        cores=cores,
        threads=threads,
        timeline_segments=timeline_segments,
        irq_events=irq_events,
        priority_inversions=priority_inversions,
        irq_storms=irq_storms,
        deadline_misses=deadline_misses,
        ipc_topology=ipc_topology,
        correlated_logs=slog2_entries,
        latency_histogram=latency_histogram,
    )
