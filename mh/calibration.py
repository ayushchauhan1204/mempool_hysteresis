"""Load the Phase 3 calibration (dev seeds only) and apply it to the base configuration."""
from __future__ import annotations

import json
from pathlib import Path

from .config import SimConfig

CAL_PATH = Path(__file__).resolve().parents[1] / "results" / "dev" / "calibration.json"


def load_config(**overrides) -> SimConfig:
    cfg = SimConfig()
    if CAL_PATH.exists():
        cal = json.loads(CAL_PATH.read_text())
        cfg = cfg.with_(**cal["values"])
    if overrides:
        cfg = cfg.with_(**overrides)
    return cfg
