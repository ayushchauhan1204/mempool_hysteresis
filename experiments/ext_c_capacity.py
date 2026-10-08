"""Extension C: bounded mempools and eviction (pre-registered in results/extensions/EXTENSIONS.md).

    python experiments/ext_c_capacity.py --calibrate   # cap levels from clean dev-seed (0-4) backlog statistics
    python experiments/ext_c_capacity.py               # runs on seeds 3000-3099 (needs the calibration)

Per seed and cap level (none / loose / mid / tight): the clean B1 and clean SARA histories, and all six
disturbances under B1, B2 and SARA, with SARA's calibrated values unchanged. Every clean run that neither evicted
nor rejected anything must show zero residue and zero evicted-divergence at every sample; the run stops otherwise.
Raw per-job results: results/extensions/raw/C/ (resumable). Output: results/extensions/ext_c_runs.csv and
results/extensions/ext_c_cap_calibration.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mh.calibration import load_config  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402
from mh.ext_metrics import capacity_metrics  # noqa: E402
from mh.policies import make_policy  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402
from mh.sim import Simulation  # noqa: E402

OUT = ROOT / "results" / "extensions"
RAW = OUT / "raw" / "C"
CAL = OUT / "ext_c_cap_calibration.json"
DEV_SEEDS = (0, 1, 2, 3, 4)
SEEDS = tuple(range(3000, 3100))
POLICIES = ("B1", "B2", "SARA")
CAP_RULE = {"loose": 1.10, "mid": 0.75, "tight": 0.50}
METRICS = ("T_det", "detected", "T_decl", "decl_censored", "T_conv", "conv_censored", "T_bk", "T_true", "FRE",
           "FRE_state", "FRE_backlog", "over_delay", "over_delay_state", "resid_at_decl", "residue_auc", "resid_10",
           "resid_60", "resid_300", "n_incidents", "incidents_after_warmup", "reopened", "announced", "requested",
           "transfers", "unnecessary", "conf_lat_mean", "unconfirmed_post")


# ------------------------------------------------------------------------------------------- calibration
def _sizes(sim, store):
    store.append([len(mp) for mp in sim.mempool])


def calibrate_caps():
    """Per-node mempool sizes of clean B1 histories on dev seeds 0-4, sampled every 1 s over [0, horizon]."""
    cfg = load_config()
    per_seed = {}
    allv = []
    for seed in DEV_SEEDS:
        sim = Simulation(build_scenario(cfg, seed, None), make_policy("B1"))
        store = []
        for t in np.arange(1.0, cfg.horizon + 1e-9, 1.0):
            sim.at(float(t) + 1e-9, _sizes, sim, store)
        sim.run()
        a = np.asarray(store)
        per_seed[seed] = dict(max=int(a.max()), q99=float(np.quantile(a, 0.99)), q50=float(np.quantile(a, 0.5)))
        allv.append(a.ravel())
    allv = np.concatenate(allv)
    M = int(allv.max())
    caps = {k: int(math.ceil(f * M)) for k, f in CAP_RULE.items()}
    rep = dict(rule="cap = ceil(factor x M), M = largest per-node mempool size in clean B1 histories of dev seeds "
                    "0-4 sampled every 1 s over [0, horizon]", factors=CAP_RULE, dev_seeds=list(DEV_SEEDS), M=M,
               q50=float(np.quantile(allv, 0.5)), q99=float(np.quantile(allv, 0.99)),
               q999=float(np.quantile(allv, 0.999)), per_seed=per_seed, caps=caps)
    OUT.mkdir(parents=True, exist_ok=True)
    CAL.write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return rep


# ------------------------------------------------------------------------------------------- runs
def _row(level, cap, seed, history, dist, pol, r, cfg, te):
    m = r["metrics"][f"{te:g}"]
    row = dict(cap_level=level, cap=cap if cap is not None else -1, seed=seed, history=history, dist=dist or "",
               policy=pol, cutoff=te, wall=r["wall"])
    for k in METRICS:
        row[k] = m[k]
    row["state_alarm"] = any(src.startswith("state") and t >= cfg.dist_start - 1e-9
                             for t, src in r["policy"]["alarms"])
    if cap is not None:
        row.update(capacity_metrics(r, te, cfg))
    else:
        row.update(evicted=0, rejected=0, refused_deliveries=0, unrepairable=0)
    if "audit_log" in r and len(r["audit_log"]) and "max_tier_post" not in row:
        a = np.asarray(r["audit_log"])
        post = a[a[:, 0] >= te - 1e-9]
        row["max_tier_post"] = int(post[:, 4].max()) if len(post) else 0
        row["share_high_post"] = float(np.mean(post[:, 4] >= 2)) if len(post) else 0.0
    return row


def _check_clean(r, cutoffs, label):
    """A clean run that dropped nothing must have zero residue and zero evicted-divergence at every sample."""
    c = r["counters"]
    if c.get("evicted", 0) == 0 and c.get("rejected", 0) == 0:
        s = r["series"]
        for te in cutoffs:
            bad = np.nansum(s[f"res@{te:g}"]) != 0 or (f"evdiv@{te:g}" in s and np.nansum(s[f"evdiv@{te:g}"]) != 0)
            if bad:
                raise AssertionError(f"{label}: clean run without evictions shows residue/evicted-divergence")
        return True
    return False


def run_job(job):
    level, cap, seed = job
    path = RAW / level / f"seed_{seed:05d}.pkl"
    if path.exists():
        return str(path)
    cfg = load_config().with_(mempool_cap=cap)
    cutoffs = sorted({cfg.t_end(d) for d in DISTURBANCES})
    rows = []
    ref = run_one(cfg, seed, None, "B1", cutoffs=cutoffs)
    pend_ref = ref["series"]["pend"]
    for pol, r in (("B1", ref), ("SARA", run_one(cfg, seed, None, "SARA", cutoffs=cutoffs, pend_ref=pend_ref))):
        for te in cutoffs:
            row = _row(level, cap, seed, "clean", None, pol, r, cfg, te)
            row["clean_no_drops_checked"] = _check_clean(r, cutoffs, f"cap {level} seed {seed} clean {pol}")
            row["res_max"] = float(np.nanmax(r["series"][f"res@{te:g}"]))
            row["evdiv_max"] = float(np.nanmax(r["series"][f"evdiv@{te:g}"])) if cap is not None else 0.0
            rows.append(row)
    for dist in DISTURBANCES:
        te = cfg.t_end(dist)
        for pol in POLICIES:
            r = run_one(cfg, seed, dist, pol, pend_ref=pend_ref)
            rows.append(_row(level, cap, seed, "disturbed", dist, pol, r, cfg, te))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(rows, f)
    os.replace(tmp, path)
    return str(path)


def main(procs=None):
    if not CAL.exists():
        raise SystemExit(f"{CAL} missing: run with --calibrate first")
    caps = json.loads(CAL.read_text())["caps"]
    levels = [("none", None)] + [(k, int(caps[k])) for k in ("loose", "mid", "tight")]
    jobs = [(lv, cap, s) for lv, cap in levels for s in SEEDS]
    procs = procs or max(1, min(14, (os.cpu_count() or 2) - 2))
    print(f"{len(jobs)} jobs: caps {levels}", flush=True)
    t0 = time.perf_counter()
    with Pool(procs) as pool:
        for k, _ in enumerate(pool.imap_unordered(run_job, jobs), 1):
            if k % 25 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)} jobs  {time.perf_counter() - t0:.0f}s", flush=True)
    rows = []
    for p in sorted(RAW.glob("*/seed_*.pkl")):
        with open(p, "rb") as f:
            rows += pickle.load(f)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "ext_c_runs.csv", index=False)
    print(f"wrote {OUT / 'ext_c_runs.csv'} ({len(df)} rows)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--procs", type=int, default=None, help="worker processes (default: CPUs - 2, at most 14)")
    a = ap.parse_args()
    if a.calibrate:
        calibrate_caps()
    else:
        main(a.procs)
