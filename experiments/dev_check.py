"""Phase 3 checks on dev seeds (plan Sections 6 and 8):
(a) the no-intervention network (B1) shows residue after at least the partition;
(b) all six policies are behaviourally distinct from one another;
(c) a per-policy summary to eyeball before spending the held-out budget."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.common import load_dir, run_many  # noqa: E402
from mh.calibration import load_config  # noqa: E402
from mh.config import POLICIES  # noqa: E402

DEV_SEEDS = [0, 1, 2, 3, 4]
OUT = Path(__file__).resolve().parents[1] / "results" / "dev" / "runs"
SIG = ["T_decl", "FRE", "T_conv", "residue_auc", "transfers", "T_det", "snapshot_ids", "resyncs"]

if __name__ == "__main__":
    cfg = load_config()
    print("config:", dict(tau_m=cfg.tau_m, eps_D=cfg.eps_D, beta=cfg.beta, eps_size=cfg.eps_size))
    run_many(DEV_SEEDS, cfg, OUT)
    df, curves, post = load_dir(OUT)
    dist_df = df[df.history == "disturbed"]

    print("\n(a) residue on the no-intervention network (B1), per disturbance:")
    b1 = dist_df[dist_df.policy == "B1"]
    print(b1.groupby("dist")[["resid_10", "resid_60", "T_conv", "T_true", "FRE"]].median().round(1))

    print("\n(b) distinctness: share of (disturbance, seed) cells where two policies' outcomes differ")
    piv = {p: dist_df[dist_df.policy == p].set_index(["dist", "seed"])[SIG].sort_index() for p in POLICIES}
    worst = []
    for a, b in itertools.combinations(POLICIES, 2):
        A, B = piv[a], piv[b]
        diff = ~np.isclose(A.fillna(-1).values, B.fillna(-1).values).all(axis=1)
        frac = diff.mean()
        worst.append((frac, a, b))
        print(f"  {a:7s} vs {b:7s}: differ in {frac:5.0%} of cells")
    print("  minimum:", min(worst))

    print("\n(c) per-policy medians across all disturbances (dev seeds):")
    cols = ["T_det", "T_decl", "T_true", "FRE", "over_delay", "resid_at_decl", "residue_auc", "transfers",
            "unnecessary", "reopened"]
    print(dist_df.groupby("policy")[cols].median().round(1).loc[list(POLICIES)])
    dist_df = dist_df.assign(inband_kB=(dist_df.announced * 36 + dist_df.requested * 36 + dist_df.transfers * 250) / 1000,
                             monitor_delta_kB=dist_df.snapshot_delta_ids * 32 / 1000)
    for col in ("T_true", "T_decl", "over_delay", "inband_kB", "monitor_delta_kB", "unnecessary"):
        print(f"\nper disturbance x policy: {col} median")
        print(dist_df.pivot_table(index="dist", columns="policy", values=col, aggfunc="median")[list(POLICIES)].round(1))
    print("\nper disturbance x policy: FRE median")
    print(dist_df.pivot_table(index="dist", columns="policy", values="FRE", aggfunc="median")[list(POLICIES)].round(1))
    print("\nper disturbance x policy: T_conv median")
    print(dist_df.pivot_table(index="dist", columns="policy", values="T_conv", aggfunc="median")[list(POLICIES)].round(1))
    clean = df[df.history == "clean"]
    print("\nclean runs: incidents after warm-up (false alarms) mean per run")
    print(clean[clean.cutoff == clean.cutoff.min()].groupby("policy")["incidents_after_warmup"].mean())
