"""Phase 4 statistics: every number the paper will quote, exported to results/numbers.json.

Tests are paired by seed (common random numbers make the pairing exact):
  Table I   (RQ1)  disturbed vs clean history, no intervention (B1)
  Table II  (RQ2/3) SARA vs B1 and SARA vs B2
  Table III (RQ4)  full SARA vs each ablation variant
Paired two-sided Wilcoxon signed-rank (zero differences dropped, 'wilcox'), Holm correction within
each table, effect size = matched-pairs rank-biserial r and the median paired difference with a
bootstrap 95% CI. Pooled results average each seed over the six disturbance types first, so the
pooled test still has one independent pair per seed.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.common import load_dir  # noqa: E402
from mh.config import DISTURBANCES, POLICIES  # noqa: E402

RAW = ROOT / "results" / "raw" / "main"
OUT = ROOT / "results"
RNG = np.random.default_rng(20261005)


# ------------------------------------------------------------------ statistics helpers
def rank_biserial(d):
    d = np.asarray(d, float)
    d = d[np.isfinite(d) & (d != 0)]
    if len(d) == 0:
        return 0.0
    ranks = stats.rankdata(np.abs(d))
    tp = ranks[d > 0].sum()
    tn = ranks[d < 0].sum()
    return float((tp - tn) / (tp + tn))


def boot_ci_median(d, n=2000):
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return [math.nan, math.nan]
    idx = RNG.integers(0, len(d), (n, len(d)))
    meds = np.median(d[idx], axis=1)
    return [float(np.quantile(meds, 0.025)), float(np.quantile(meds, 0.975))]


def paired_test(a, b):
    """a, b aligned arrays (same seeds). Returns dict for a - b."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    d = a - b
    nz = int(np.sum(d != 0))
    if nz == 0:
        p = 1.0
    else:
        try:
            p = float(stats.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided").pvalue)
        except ValueError:
            p = 1.0
    return dict(n=int(len(d)), n_nonzero=nz, median_a=float(np.median(a)) if len(a) else math.nan,
                median_b=float(np.median(b)) if len(b) else math.nan,
                mean_a=float(np.mean(a)) if len(a) else math.nan, mean_b=float(np.mean(b)) if len(b) else math.nan,
                median_diff=float(np.median(d)) if len(d) else math.nan,
                mean_diff=float(np.mean(d)) if len(d) else math.nan,
                ci95_median_diff=boot_ci_median(d), p=p, r_rb=rank_biserial(d))


def holm(results):
    """In-place Holm correction over a list of result dicts with key 'p'."""
    ps = np.array([r["p"] for r in results], float)
    order = np.argsort(ps)
    m = len(ps)
    adj = np.empty(m)
    running = 0.0
    for k, i in enumerate(order):
        running = max(running, (m - k) * ps[i])
        adj[i] = min(1.0, running)
    for r, a in zip(results, adj):
        r["p_holm"] = float(a)
        r["sig"] = "***" if a < 0.001 else "**" if a < 0.01 else "*" if a < 0.05 else "n.s."
    return results


def describe(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return dict(n=0)
    return dict(n=int(len(x)), mean=float(np.mean(x)), median=float(np.median(x)),
                q25=float(np.quantile(x, .25)), q75=float(np.quantile(x, .75)), max=float(np.max(x)))


# ------------------------------------------------------------------ derived quantities
def add_derived(df):
    df = df.copy()
    df["inband_kB"] = (df.announced * 36 + df.requested * 36 + df.transfers * 250) / 1000.0
    df["monitor_kB"] = df.snapshot_delta_ids * 32 / 1000.0
    df["monitor_full_kB"] = df.snapshot_ids * 32 / 1000.0
    return df


def ordering_distortion(post, seed, dist, pol, cutoff):
    """1 - Kendall tau-b between confirmation times of the identical post-recovery workload."""
    kc = (seed, "clean", None, "B1", cutoff)
    kd = (seed, "disturbed", dist, pol, cutoff)
    if kc not in post or kd not in post:
        return math.nan
    ids_c, lat_c = post[kc]
    ids_d, lat_d = post[kd]
    if len(ids_c) != len(ids_d) or not np.array_equal(ids_c, ids_d):
        return math.nan
    ok = np.isfinite(lat_c) & np.isfinite(lat_d)
    if ok.sum() < 3:
        return math.nan
    if np.allclose(lat_c[ok], lat_d[ok]):
        return 0.0
    tau = stats.kendalltau(lat_c[ok], lat_d[ok]).statistic
    return float(1.0 - tau)


def main(raw=RAW):
    t0 = time.time()
    df, curves, post = load_dir(raw)
    df = add_derived(df)
    seeds = sorted(df.seed.unique())
    cfg = json.loads((Path(raw) / "config.json").read_text())
    cal = json.loads((ROOT / "results" / "dev" / "calibration.json").read_text())
    clean = df[df.history == "clean"]
    dist = df[df.history == "disturbed"]

    def cell(pol, d, metric):
        x = dist[(dist.policy == pol) & (dist.dist == d)].set_index("seed")[metric]
        return x.reindex(seeds)

    def clean_cell(pol, cutoff, metric):
        x = clean[(clean.policy == pol) & (clean.cutoff == cutoff)].set_index("seed")[metric]
        return x.reindex(seeds)

    numbers = dict(meta=dict(generated=time.strftime("%Y-%m-%d %H:%M"), n_seeds=len(seeds),
                             seeds=[int(seeds[0]), int(seeds[-1])], config=cfg, calibration=cal,
                             runs=int(df.drop_duplicates(["seed", "history", "dist", "policy"]).shape[0])))

    # ---------------- Table I: RQ1 hysteresis, B1 disturbed vs B1 clean ----------------
    rq1_metrics = ["residue_auc", "T_conv", "T_bk", "excess_backlog_auc", "conf_lat_mean", "conf_lat_p95",
                   "conf_lat_mean_cens", "stale_rate", "resid_10", "resid_60", "resid_300"]
    t1 = {}
    fam = []
    for d in DISTURBANCES:
        te = cfg["dist_start"] + (cfg["burst_duration"] if d == "burst" else cfg["dist_duration"])
        t1[d] = {}
        for m in rq1_metrics:
            r = paired_test(cell("B1", d, m).values, clean_cell("B1", te, m).values)
            t1[d][m] = r
            fam.append(r)
        # ordering distortion vs clean (one-sample against 0)
        od = np.array([ordering_distortion(post, s, d, "B1", te) for s in seeds])
        r = paired_test(od, np.zeros_like(od))
        t1[d]["ordering_distortion"] = r
        fam.append(r)
        # how often B1's declaration came before true state convergence
        decl = cell("B1", d, "T_decl").values
        conv = cell("B1", d, "T_conv").values
        t1[d]["share_declared_before_state_converged"] = float(np.mean(decl < conv))
        t1[d]["T_conv_censored_share"] = float(cell("B1", d, "conv_censored").astype(float).mean())
    holm(fam)
    numbers["table1_rq1"] = t1

    # ---------------- descriptive table per policy and disturbance ----------------
    desc_metrics = ["T_det", "T_decl", "T_conv", "T_bk", "T_true", "FRE", "FRE_state", "FRE_backlog",
                    "over_delay", "resid_at_decl", "residue_auc", "inband_kB", "transfers", "unnecessary",
                    "monitor_kB", "monitor_full_kB", "reopened", "conf_lat_mean", "stale_rate"]
    desc = {}
    for d in DISTURBANCES:
        desc[d] = {}
        for pol in POLICIES:
            sub = dist[(dist.policy == pol) & (dist.dist == d)]
            desc[d][pol] = {m: describe(sub[m]) for m in desc_metrics}
            desc[d][pol]["detected_share"] = float(sub.detected.astype(float).mean())
            desc[d][pol]["premature_share"] = float((sub.FRE_state > 0).astype(float).mean())
            desc[d][pol]["conv_censored_share"] = float(sub.conv_censored.astype(float).mean())
            desc[d][pol]["true_censored_share"] = float(sub.true_censored.astype(float).mean())
    numbers["descriptive"] = desc

    # pooled over disturbance types: one value per seed (mean over the six types)
    pooled = {}
    for pol in POLICIES:
        sub = dist[dist.policy == pol].groupby("seed")[desc_metrics].mean().reindex(seeds)
        pooled[pol] = {m: describe(sub[m]) for m in desc_metrics}
    numbers["pooled_descriptive"] = pooled

    # ---------------- Table II: SARA vs baselines ----------------
    cmp_metrics = ["FRE_state", "FRE_backlog", "FRE", "over_delay", "T_conv", "T_decl", "residue_auc",
                   "inband_kB", "unnecessary", "conf_lat_mean"]
    t2 = {}
    fam = []
    for base in ("B1", "B2"):
        key = f"SARA_vs_{base}"
        t2[key] = {}
        for d in DISTURBANCES:
            t2[key][d] = {}
            for m in cmp_metrics:
                r = paired_test(cell("SARA", d, m).values, cell(base, d, m).values)
                t2[key][d][m] = r
                fam.append(r)
        t2[key]["pooled"] = {}
        for m in cmp_metrics:
            a = dist[dist.policy == "SARA"].groupby("seed")[m].mean().reindex(seeds)
            b = dist[dist.policy == base].groupby("seed")[m].mean().reindex(seeds)
            r = paired_test(a.values, b.values)
            t2[key]["pooled"][m] = r
            fam.append(r)
    holm(fam)
    numbers["table2_policies"] = t2

    # downstream: post-recovery confirmation latency relative to the clean history, per policy
    downstream = {}
    for d in DISTURBANCES:
        te = cfg["dist_start"] + (cfg["burst_duration"] if d == "burst" else cfg["dist_duration"])
        downstream[d] = {}
        for pol in ("B1", "B2", "SARA"):
            delta = cell(pol, d, "conf_lat_mean").values - clean_cell("B1", te, "conf_lat_mean").values
            od = np.array([ordering_distortion(post, s, d, pol, te) for s in seeds])
            downstream[d][pol] = dict(conf_lat_delta=describe(delta), ordering_distortion=describe(od))
    numbers["downstream_by_policy"] = downstream

    # ---------------- Table III: ablation ----------------
    abl_metrics = ["FRE_state", "FRE_backlog", "FRE", "over_delay", "T_conv", "resid_at_decl", "inband_kB",
                   "unnecessary", "reopened"]
    t3 = {}
    fam = []
    for var in ("SARA-D", "SARA-R", "SARA-V"):
        key = f"SARA_vs_{var}"
        t3[key] = {}
        for d in DISTURBANCES:
            t3[key][d] = {}
            for m in abl_metrics:
                r = paired_test(cell("SARA", d, m).values, cell(var, d, m).values)
                t3[key][d][m] = r
                fam.append(r)
        t3[key]["pooled"] = {}
        for m in abl_metrics:
            a = dist[dist.policy == "SARA"].groupby("seed")[m].mean().reindex(seeds)
            b = dist[dist.policy == var].groupby("seed")[m].mean().reindex(seeds)
            r = paired_test(a.values, b.values)
            t3[key]["pooled"][m] = r
            fam.append(r)
    holm(fam)
    numbers["table3_ablation"] = t3

    # ---------------- false alarms in clean runs ----------------
    c0 = clean[clean.cutoff == clean.cutoff.min()]
    numbers["false_alarms_clean"] = {p: dict(mean_incidents_per_run=float(c0[c0.policy == p].incidents_after_warmup.mean()),
                                             runs_with_any=float((c0[c0.policy == p].incidents_after_warmup > 0).mean()))
                                     for p in c0.policy.unique()}
    numbers["clean_reference"] = {m: describe(c0[c0.policy == "B1"][m]) for m in
                                  ("conf_lat_mean", "conf_lat_p95", "stale_rate", "T_conv")}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "numbers.json").write_text(json.dumps(numbers, indent=1, default=float))
    df.to_csv(OUT / "all_runs.csv", index=False)
    print(f"numbers.json written ({len(seeds)} seeds, {len(df)} metric rows) in {time.time() - t0:.0f}s")
    return numbers, df, curves, post


if __name__ == "__main__":
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else RAW
    main(raw)
