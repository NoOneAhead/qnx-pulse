"""Authentic QNX 8.0 `slog2info` output parser.

Supports standard QNX 8.0 `slog2info` output variants:
- Default:  `Dec 21 21:12:00.029 adas_aeb.41370 events* 101 Message text`
- `-S`:     `Dec 21 21:12:00.029 adas_aeb.41370 events* WARNING 101 Message text`
- `-S -t`:  `Dec 21 21:12:00.029 adas_aeb.41370 events* WARNING 2 101 Message text`
- `-f`:     `1734815520.029 adas_aeb.41370 events* ERROR 2 101 Message text`
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from qnx_pulse.models import Slog2Entry

SEVERITY_TOKENS = {
    "SHUTDOWN": "CRITICAL",
    "CRITICAL": "CRITICAL",
    "SLOG2_CRITICAL": "CRITICAL",
    "ERROR": "ERROR",
    "SLOG2_ERROR": "ERROR",
    "WARNING": "WARNING",
    "SLOG2_WARNING": "WARNING",
    "NOTICE": "NOTICE",
    "SLOG2_NOTICE": "NOTICE",
    "INFO": "INFO",
    "SLOG2_INFO": "INFO",
    "DEBUG1": "DEBUG1",
    "SLOG2_DEBUG1": "DEBUG1",
    "DEBUG2": "DEBUG2",
    "SLOG2_DEBUG2": "DEBUG2",
}

CALENDAR_RE = re.compile(
    r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+(?P<rest>.+)$"
)
EPOCH_RE = re.compile(
    r"^(?P<ts>\d{9,12}\.\d{3,6})\s+(?P<rest>.+)$"
)
BUFSET_PID_RE = re.compile(r"^(?P<bset>[^\s]+)\.(?P<pid>\d+)$")


def _parse_calendar_ms(ts_str: str) -> float:
    try:
        dt = datetime.strptime(f"2026 {ts_str}", "%Y %b %d %H:%M:%S.%f")
        return dt.timestamp() * 1000.0
    except ValueError:
        return 0.0


def parse_slog2(text: str) -> list[Slog2Entry]:
    """Parse QNX 8.0 `slog2info` log text into structured Slog2Entry records."""
    entries: list[Slog2Entry] = []
    raw_times: list[float] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        cm = CALENDAR_RE.match(line)
        em = EPOCH_RE.match(line) if not cm else None
        if cm:
            ts_str = cm.group("ts")
            ts_ms = _parse_calendar_ms(ts_str)
            rest = cm.group("rest")
        elif em:
            ts_str = em.group("ts")
            ts_ms = float(ts_str) * 1000.0
            rest = em.group("rest")
        else:
            continue

        tokens = rest.split()
        if len(tokens) < 4:
            continue

        bm = BUFSET_PID_RE.match(tokens[0])
        if bm:
            buffer_set = bm.group("bset")
            pid = int(bm.group("pid"))
        else:
            buffer_set = tokens[0]
            pid = 0

        raw_buf = tokens[1]
        is_oldest = raw_buf.endswith("*")
        buffer_name = raw_buf.rstrip("*")

        idx = 2
        severity = "INFO"
        if idx < len(tokens) and tokens[idx].upper() in SEVERITY_TOKENS:
            severity = SEVERITY_TOKENS[tokens[idx].upper()]
            idx += 1

        tid: Optional[int] = None
        code = 0
        # Check if we have two integers (`tid code`) or one (`code`)
        if idx + 1 < len(tokens) and tokens[idx].isdigit() and tokens[idx + 1].isdigit():
            tid = int(tokens[idx])
            code = int(tokens[idx + 1])
            idx += 2
        elif idx < len(tokens) and tokens[idx].isdigit():
            code = int(tokens[idx])
            idx += 1

        message = " ".join(tokens[idx:]) if idx < len(tokens) else ""
        # Infer severity from message if `-S` was not passed
        if severity == "INFO":
            upper_msg = message.upper()
            if "CRITICAL" in upper_msg or "DEADLINE MISS" in upper_msg or "FAULT" in upper_msg:
                severity = "CRITICAL"
            elif "ERROR" in upper_msg or "FAILED" in upper_msg:
                severity = "ERROR"
            elif "WARN" in upper_msg or "INVERSION" in upper_msg or "STORM" in upper_msg:
                severity = "WARNING"

        raw_times.append(ts_ms)
        entries.append(
            Slog2Entry(
                timestamp_str=ts_str,
                timestamp_ms=ts_ms,
                buffer_set=buffer_set,
                pid=pid,
                buffer_name=buffer_name,
                is_oldest=is_oldest,
                severity=severity,
                tid=tid,
                code=code,
                message=message,
            )
        )

    if entries and raw_times:
        base_ms = min(raw_times)
        for entry in entries:
            entry.timestamp_ms = round(entry.timestamp_ms - base_ms, 3)

    return entries
