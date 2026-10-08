"""Working-model demo: replay one disturbance under B1, B2 and SARA and show what each one
believed, what it did, and what was actually true.

    python demo.py                         # partition, held-out seed 1000
    python demo.py --dist burst --seed 1003
    python demo.py --dist all              # one line per disturbance type

Prints each policy's audit trail and an outcome table, and saves
results/demo_<dist>_<seed>.png (residue and excess backlog over time).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from mh.calibration import load_config  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402

POLS = ("B1", "B2", "SARA")


def describe(cfg, seed, dist):
    scn = build_scenario(cfg, seed, dist)
    d = scn.disturbance
    what = {
        "partition": f"network split; minority side = nodes {list(d.group_a)}",
        "isolation": f"node(s) {list(d.nodes)} cut off from all peers",
        "loss": f"{cfg.loss_p:.0%} packet loss on every link of nodes {list(d.nodes)}",
        "latency": f"latency x{cfg.latency_mult:g} on every link of nodes {list(d.nodes)}",
        "asymmetric": f"outbound traffic of nodes {list(d.nodes)} blackholed",
        "burst": f"transaction arrival rate x{cfg.burst_factor:g}",
    }[dist]
    return (f"{cfg.n_nodes} nodes, {len(scn.edges)} links, {len(scn.created)} transactions, "
            f"{len(scn.block_times)} scheduled blocks\n"
            f"disturbance: {dist} from t={d.start:.0f}s to t={d.end:.0f}s: {what}")


def fmt(v, unit="s"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "never"
    return f"{v:.0f}{unit}"


def one(cfg, seed, dist, verbose=True, plot=True):
    ref = run_one(cfg, seed, None, "B1", cutoffs=[cfg.t_end(dist)])
    pend_ref = ref["series"]["pend"]
    runs = {p: run_one(cfg, seed, dist, p, keep_log=True, pend_ref=pend_ref) for p in POLS}
    te = cfg.t_end(dist)
    if verbose:
        print("=" * 100)
        print(describe(cfg, seed, dist))
        for p in POLS:
            r = runs[p]
            print(f"\n--- {p} audit trail (times relative to disturbance end; first 12 entries) ---")
            log = r["log"]
            for t, msg in log[:12]:
                print(f"  t{t - te:+7.1f}s  {msg}")
            if len(log) > 12:
                print(f"  ... {len(log) - 12} more entries")
        print("\n" + "-" * 100)
        print(f"{'policy':6s} {'detected':>9s} {'declared':>9s} {'state ok':>9s} {'backlog ok':>11s} "
              f"{'FRE_state':>10s} {'FRE':>7s} {'residue@decl':>13s} {'traffic':>9s}")
    rows = {}
    for p in POLS:
        m = runs[p]["metrics"][f"{te:g}"]
        kb = (m["announced"] * 36 + m["requested"] * 36 + m["transfers"] * 250) / 1000
        rows[p] = m
        if verbose:
            print(f"{p:6s} {fmt(m['T_det']):>9s} {fmt(m['T_decl']):>9s} {fmt(m['T_conv']):>9s} "
                  f"{fmt(m['T_bk']):>11s} {fmt(m['FRE_state']):>10s} {fmt(m['FRE']):>7s} "
                  f"{m['resid_at_decl']:>13.0f} {kb:>7.0f}kB")
    if verbose:
        print("detected = after disturbance start; declared / state ok / backlog ok = after disturbance end.")
        print("FRE = seconds the policy reported 'recovered' while the true state had not recovered.")
    if plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 3.2))
        col = {"B1": "#c0392b", "B2": "#e08e0b", "SARA": "#1f5fa8"}
        dur = te - cfg.dist_start
        ax.axvspan(-dur, 0, color="#f5c6c0", alpha=0.5, lw=0, label="disturbance")
        for p in POLS:
            s = runs[p]["series"]
            t = np.asarray(s["t"]) - te
            ax.plot(t, np.nan_to_num(s[f"res@{te:g}"]), color=col[p], lw=1.3, label=f"residue, {p}")
            ax.axvline(rows[p]["T_decl"], color=col[p], ls=":", lw=1)
        ax2 = ax.twinx()
        s = runs["B1"]["series"]
        ax2.plot(np.asarray(s["t"]) - te, np.clip(np.asarray(s["pend"]) - np.asarray(pend_ref), 0, None),
                 color="gray", ls="--", lw=1, label="excess backlog, B1")
        ax2.set_ylabel("excess backlog (tx)", color="gray")
        ax.set_xlim(-dur - 30, 480)
        ax.set_xlabel("time since disturbance ended (s)   (dotted lines: when each policy declared recovery)")
        ax.set_ylabel("residue (tx)")
        ax.set_title(f"{dist}, seed {seed}")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=7, frameon=False, loc="upper right")
        out = ROOT / "results" / f"demo_{dist}_{seed}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=150)
        plt.close(fig)
        if verbose:
            print(f"\nplot saved to {out}")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dist", default="partition", choices=list(DISTURBANCES) + ["all"])
    ap.add_argument("--seed", type=int, default=1000)
    args = ap.parse_args()
    cfg = load_config()
    if args.dist == "all":
        print(f"{'disturbance':12s} " + "  ".join(f"{p + ' FRE_state':>15s}" for p in POLS))
        for d in DISTURBANCES:
            rows = one(cfg, args.seed, d, verbose=False, plot=False)
            print(f"{d:12s} " + "  ".join(f"{fmt(rows[p]['FRE_state']):>15s}" for p in POLS))
    else:
        one(cfg, args.seed, args.dist)
