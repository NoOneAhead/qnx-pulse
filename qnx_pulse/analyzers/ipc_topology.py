"""QNX 8.0 IPC & Resource Manager Dependency Topology Builder."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from qnx_pulse.models import IpcEdge, IpcNode, IpcTopology, ThreadMetrics
from qnx_pulse.parsers.traceprinter import ParsedTrace


def _p99(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)
    return round(ordered[idx], 2)


def _short_name(path: str) -> str:
    return path.rstrip("/").split("/")[-1] if path else "unknown"


def build_ipc_topology(
    parsed: ParsedTrace,
    completed_ipc: list[dict[str, Any]],
    pulse_events: list[dict[str, Any]],
    inversion_rcvid_set: set[str],
    threads: list[ThreadMetrics],
) -> IpcTopology:
    """Build directed process-level IPC & Resource Manager dependency graph."""
    pids_present: set[int] = set(parsed.process_names.keys())
    for t in threads:
        pids_present.add(t.pid)
    for tx in completed_ipc:
        pids_present.add(tx["client_pid"])
        pids_present.add(tx["server_pid"])
    for pe in pulse_events:
        pids_present.add(pe["src_pid"])
        pids_present.add(pe["dst_pid"])

    # Aggregate sync message edges: (src_pid, dst_pid) -> list of txs
    msg_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    senders: set[int] = set()
    receivers: set[int] = set()

    for tx in completed_ipc:
        s, d = tx["client_pid"], tx["server_pid"]
        senders.add(s)
        receivers.add(d)
        msg_groups[(s, d)].append(tx)

    pulse_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for pe in pulse_events:
        s, d = pe["src_pid"], pe["dst_pid"]
        senders.add(s)
        receivers.add(d)
        pulse_groups[(s, d)].append(pe)

    edges: list[IpcEdge] = []
    anomalous_pids: dict[int, str] = {}

    for (s, d), txs in sorted(msg_groups.items()):
        lats = [t["latency_us"] for t in txs]
        has_inv = any(t["rcvid"] in inversion_rcvid_set for t in txs)
        inherited = all(t["priority_inherited"] for t in txs)
        if has_inv:
            anomalous_pids[d] = "Priority inheritance disabled (_NTO_CHF_FIXED_PRIORITY) / inversion hotspot"
            anomalous_pids.setdefault(s, "Blocked waiting on priority-inverted IPC server")
        edges.append(
            IpcEdge(
                source=f"pid:{s}",
                target=f"pid:{d}",
                kind="MSG_SYNC",
                count=len(txs),
                avg_latency_us=round(sum(lats) / len(lats), 2),
                max_latency_us=round(max(lats), 2),
                p99_latency_us=_p99(lats),
                priority_inherited=inherited,
                has_inversion=has_inv,
                rcvid_samples=[t["rcvid"] for t in txs[:5]],
            )
        )

    for (s, d), pes in sorted(pulse_groups.items()):
        edges.append(
            IpcEdge(
                source=f"pid:{s}",
                target=f"pid:{d}",
                kind="PULSE_ASYNC",
                count=len(pes),
                avg_latency_us=12.0,
                max_latency_us=25.0,
                p99_latency_us=25.0,
                priority_inherited=False,
                has_inversion=False,
                rcvid_samples=[],
            )
        )

    # Group thread metrics per pid
    threads_by_pid: dict[int, list[ThreadMetrics]] = defaultdict(list)
    for t in threads:
        threads_by_pid[t.pid].append(t)

    nodes: list[IpcNode] = []
    for pid in sorted(pids_present):
        # Skip idle procnto if it has zero edges and zero active threads
        tlist = threads_by_pid.get(pid, [])
        has_edge = any(e.source == f"pid:{pid}" or e.target == f"pid:{pid}" for e in edges)
        if pid == 1 and not has_edge and not tlist:
            continue

        pname = _short_name(parsed.process_names.get(pid, f"pid_{pid}"))
        res_paths = parsed.resmgr_paths.get(pid, [])
        if pid == 1 or "procnto" in pname:
            role = "KERNEL"
        elif res_paths or (pid in receivers and pid not in senders):
            role = "RESMGR"
        elif pid in senders and pid not in receivers:
            role = "CLIENT"
        else:
            role = "HYBRID"

        prios = [p for t in tlist for p in (t.min_priority, t.max_priority)]
        if prios:
            pmin, pmax = min(prios), max(prios)
            prio_range = f"{pmin}" if pmin == pmax else f"{pmin}-{pmax}"
        else:
            prio_range = "10"

        cpu_pct = round(sum(t.cpu_share_pct for t in tlist), 2)
        has_dl_miss = any(t.deadline_misses > 0 for t in tlist)
        anomaly_note = anomalous_pids.get(pid)
        if has_dl_miss and not anomaly_note:
            anomaly_note = "Real-time deadline miss recorded"

        nodes.append(
            IpcNode(
                id=f"pid:{pid}",
                pid=pid,
                name=pname,
                role=role,
                resource_paths=res_paths,
                priority_range=prio_range,
                thread_count=max(1, len(tlist)),
                avg_cpu_pct=cpu_pct,
                has_anomaly=(anomaly_note is not None),
                anomaly_note=anomaly_note,
            )
        )

    # Identify critical path (edge with highest max latency or inversion)
    critical_path: list[str] = []
    if edges:
        hottest = max(edges, key=lambda e: (1 if e.has_inversion else 0, e.max_latency_us))
        node_map = {n.id: n.name for n in nodes}
        critical_path = [
            node_map.get(hottest.source, hottest.source),
            node_map.get(hottest.target, hottest.target),
        ]

    return IpcTopology(
        nodes=nodes,
        edges=edges,
        total_messages=len(completed_ipc),
        total_pulses=len(pulse_events),
        critical_path=critical_path,
    )
