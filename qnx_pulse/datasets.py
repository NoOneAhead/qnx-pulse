"""Dataset loader & registry for built-in QNX 8.0 benchmark scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = REPO_ROOT / "datasets"


def list_scenarios() -> list[dict[str, Any]]:
    """Return metadata for all built-in QNX 8.0 scenarios."""
    if not DATASETS_DIR.exists():
        return []
    scenarios: list[dict[str, Any]] = []
    for meta_path in sorted(DATASETS_DIR.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            scenarios.append(meta)
        except Exception:
            continue
    # Sort so ADAS AEB comes first, Surgical Robot second, Healthy Baseline third
    order = {
        "adas_aeb_inversion": 0,
        "surgical_robot_irq_storm": 1,
        "amr_fleet_healthy_baseline": 2,
    }
    scenarios.sort(key=lambda s: order.get(s.get("id", ""), 99))
    return scenarios


def load_scenario(scenario_id: str) -> Optional[dict[str, Any]]:
    """Load full text artifacts (trace, slog2, buildfile, secpol, meta) for a scenario."""
    sdir = DATASETS_DIR / scenario_id
    meta_path = sdir / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    def _read(name: str) -> str:
        p = sdir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return {
        "meta": meta,
        "trace_text": _read("trace.txt"),
        "slog2_text": _read("slog2.txt"),
        "buildfile_text": _read("system.build"),
        "secpol_text": _read("system.secpol"),
    }
