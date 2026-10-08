"""Extension A: confirmation delay and block composition (user-visible harm).
Definitions, hypotheses, seeds and configs are pre-registered in results/extensions/EXTENSIONS.md.

Why this re-simulates: the stored main-study results keep per-run metrics only (results/all_runs.csv); the
per-seed pickles (results/raw/main/seed_*.pkl) are not on disk and never held per-transaction confirmation
times for transactions created before or during the disturbance, nor block contents. So the main study's
B1/B2/SARA runs are re-run here with the unchanged calibrated configuration (deterministic, so bit-identical to
the stored runs; ext_analyze.py checks every re-run against all_runs.csv) and the extra quantities are recorded.

  heldout      seeds 1000-1199: the main study's own runs, re-measured
  replication  seeds 3000-3099: fresh extension seeds

    python experiments/ext_a_confirmation.py            # about 5 min on 14 processes
Output: results/extensions/ext_a_runs.csv (one row per run; clean-history rows have history == "clean")
"""
from __future__ import annotations

import os
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
from mh.ext_metrics import (best_chain, block_composition, confirmation_times, delay_summary,  # noqa: E402
                            excess_summary, window_ids, windows)
from mh.runner import run_one  # noqa: E402

OUT = ROOT / "results" / "extensions"
SAMPLES = {"heldout": range(1000, 1200), "replication": range(3000, 3100)}
POLICIES = ("B1", "B2", "SARA")
MAIN_COLS = ("T_det", "T_decl", "T_conv", "T_bk", "T_true", "FRE", "FRE_state", "FRE_backlog", "over_delay",
             "resid_at_decl", "residue_auc", "conf_lat_mean", "unconfirmed_post", "premature", "decl_censored",
             "conv_censored", "announced", "requested", "transfers")


def _window_stats(row, cfg, te, created, is_base, conf, conf_c=None):
    for w, (lo, hi) in windows(cfg, te).items():
        ids = window_ids(created, is_base, lo, hi)
        for k, v in delay_summary(created, conf, ids, cfg.horizon).items():
            row[f"{w}_{k}"] = v
        if conf_c is not None:
            for k, v in excess_summary(created, conf, conf_c, ids, cfg.horizon).items():
                row[f"{w}_x_{k}"] = v


def seed_rows(job):
    sample, seed = job
    cfg = load_config()
    cutoffs = sorted({cfg.t_end(d) for d in DISTURBANCES})
    ref = run_one(cfg, seed, None, "B1", cutoffs=cutoffs, keep_log=True)
    sim_c = ref.pop("sim")
    conf_c = confirmation_times(sim_c)
    chain_c = best_chain(sim_c)
    pend_ref = ref["series"]["pend"]
    rows = []
    for te in cutoffs:
        row = dict(sample=sample, seed=seed, history="clean", dist="", policy="B1", cutoff=te)
        _window_stats(row, cfg, te, sim_c.scn.created, sim_c.scn.is_base, conf_c)
        rows.append(row)
    del sim_c
    for dist in DISTURBANCES:
        te = cfg.t_end(dist)
        for pol in POLICIES:
            r = run_one(cfg, seed, dist, pol, keep_log=True, pend_ref=pend_ref)
            sim = r.pop("sim")
            scn = sim.scn
            conf_d = confirmation_times(sim)
            m = r["metrics"][f"{te:g}"]
            row = dict(sample=sample, seed=seed, history="disturbed", dist=dist, policy=pol, cutoff=te)
            _window_stats(row, cfg, te, scn.created, scn.is_base, conf_d, conf_c)
            for k, v in block_composition(best_chain(sim), chain_c, te, te + cfg.post_workload_window,
                                          scn.is_base).items():
                row[f"blk_{k}"] = v
            extra = np.nonzero(~scn.is_base)[0]
            row["burst_extra_n"] = int(len(extra))
            row["burst_extra_never"] = int(np.sum(~np.isfinite(conf_d[extra]))) if len(extra) else 0
            for c in MAIN_COLS:
                row[f"m_{c}"] = m[c]
            rows.append(row)
            del sim, r
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(s, seed) for s, seeds in SAMPLES.items() for seed in seeds]
    procs = max(1, min(14, (os.cpu_count() or 2) - 2))
    t0 = time.perf_counter()
    rows = []
    with Pool(procs) as pool:
        for k, rs in enumerate(pool.imap_unordered(seed_rows, jobs), 1):
            rows += rs
            if k % 25 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)} seeds  {time.perf_counter() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows).sort_values(["sample", "seed", "history", "dist", "policy", "cutoff"])
    df.to_csv(OUT / "ext_a_runs.csv", index=False)
    print(f"wrote {OUT / 'ext_a_runs.csv'}  ({len(df)} rows, {time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
