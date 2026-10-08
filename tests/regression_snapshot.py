"""Regression snapshot of the simulator's default behaviour, recorded before the extensions were added.

compute_snapshot() runs a fixed set of runs with the calibrated configuration (seeds 1000-1001, all six
disturbances under B1/B2/SARA, plus the clean B1 and SARA histories) and records, per run, every metric and a
SHA-256 hash of every series, the policy record and log, the monitor log, counters, chain statistics and the
post-workload arrays; per (seed, disturbance) it also hashes the seed-fixed scenario.

    python tests/regression_snapshot.py     # writes tests/regression_snapshot.json

tests/test_regression.py recomputes the snapshot and requires an exact match, so with every extension switched
off (the default) each run must be bit-for-bit identical to the recorded one.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mh.calibration import load_config  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent / "regression_snapshot.json"
SEEDS = (1000, 1001)
POLICIES = ("B1", "B2", "SARA")
CLEAN_POLICIES = ("B1", "SARA")


def _enc(v):
    """JSON-safe, exact encoding of a scalar (floats round-trip exactly through repr)."""
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return v
    return v


def _hash_array(a) -> str:
    a = np.ascontiguousarray(np.asarray(a))
    h = hashlib.sha256()
    h.update(str(a.dtype).encode())
    h.update(str(a.shape).encode())
    h.update(a.tobytes())
    return h.hexdigest()


def _hash_obj(obj) -> str:
    return hashlib.sha256(repr(obj).encode()).hexdigest()


def _record(r: dict) -> dict:
    r = dict(r)
    r.pop("sim", None)
    rec = dict(
        metrics={c: {k: _enc(v) for k, v in sorted(m.items())} for c, m in r["metrics"].items()},
        series={k: _hash_array(v) for k, v in sorted(r["series"].items())},
        policy=_hash_obj(r["policy"]),
        log=_hash_obj(r.get("log")),
        monitor_log=_hash_obj(r["monitor_log"]),
        counters={k: _enc(v) for k, v in sorted(r["counters"].items())},
        chain={k: _enc(v) for k, v in sorted(r["chain"].items())},
        post={c: {k: _hash_array(v) for k, v in sorted(w.items())} for c, w in r["post_workload"].items()},
    )
    if "audit_log" in r:
        rec["audit_log"] = _hash_array(r["audit_log"])
    return rec


def _scenario_hash(cfg, seed, dist) -> str:
    s = build_scenario(cfg, seed, dist)
    d = s.disturbance
    h = hashlib.sha256()
    h.update(repr((s.edges, s.peers, s.lat, s.n_base, s.t_end, d.kind, d.start, d.end, d.group_a, d.nodes)).encode())
    for a in (s.created, s.origin, s.fee, s.is_base, s.block_times, s.block_miners):
        h.update(_hash_array(a).encode())
    return h.hexdigest()


def compute_snapshot() -> dict:
    cfg = load_config()
    cutoffs = sorted({cfg.t_end(d) for d in DISTURBANCES})
    runs, scenarios = {}, {}
    for seed in SEEDS:
        ref = run_one(cfg, seed, None, "B1", cutoffs=cutoffs, keep_log=True)
        pend_ref = ref["series"]["pend"]
        runs[f"{seed}/clean/B1"] = _record(ref)
        for pol in CLEAN_POLICIES:
            if pol != "B1":
                runs[f"{seed}/clean/{pol}"] = _record(run_one(cfg, seed, None, pol, cutoffs=cutoffs, keep_log=True,
                                                              pend_ref=pend_ref))
        scenarios[f"{seed}/clean"] = _scenario_hash(cfg, seed, None)
        for dist in DISTURBANCES:
            scenarios[f"{seed}/{dist}"] = _scenario_hash(cfg, seed, dist)
            for pol in POLICIES:
                runs[f"{seed}/{dist}/{pol}"] = _record(run_one(cfg, seed, dist, pol, keep_log=True, pend_ref=pend_ref))
    return dict(config={k: _enc(v) for k, v in cfg.as_dict().items()}, seeds=list(SEEDS), runs=runs,
                scenarios=scenarios)


if __name__ == "__main__":
    snap = compute_snapshot()
    SNAPSHOT.write_text(json.dumps(snap, indent=1, sort_keys=True))
    print(f"wrote {SNAPSHOT} ({len(snap['runs'])} runs, {len(snap['scenarios'])} scenarios)")
