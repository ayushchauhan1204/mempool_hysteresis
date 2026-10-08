"""Extension statistics, tables and figures (analysis pre-registered in results/extensions/EXTENSIONS.md).

Reads only stored run tables: results/extensions/ext_{a,b,c}_runs.csv (and results/all_runs.csv for the
Extension A reproduction check). Writes results/extensions/ext_numbers.json, figures in
results/extensions/figures/, and the generated results section of results/extensions/EXTENSIONS.md (between the
RESULTS markers; the pre-registration and change log are never touched). Statistical helpers (paired Wilcoxon,
Holm, rank-biserial r, bootstrap CI of the median difference) are reused unchanged from experiments/analyze.py.

    python experiments/ext_analyze.py
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.analyze import describe, holm, paired_test  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402

EXT = ROOT / "results" / "extensions"
FIG = EXT / "figures"
DOC = EXT / "EXTENSIONS.md"
POL = ("B1", "B2", "SARA")
LAB = dict(partition="Partition", isolation="Node isolation", loss="Packet loss", latency="Latency spike",
           asymmetric="Asymmetric link", burst="Transaction burst")
PCOL = {"B1": "#c0392b", "B2": "#e08e0b", "SARA": "#1f5fa8"}
BOOT = np.random.default_rng(7)


# ------------------------------------------------------------------------------------------- helpers
def boot_mean(x, n=2000):
    """Mean with a 2000-resample bootstrap 95% CI (descriptive)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return dict(n=0, mean=math.nan, ci95=[math.nan, math.nan])
    bs = BOOT.choice(x, (n, len(x))).mean(axis=1)
    return dict(n=int(len(x)), mean=float(x.mean()), ci95=[float(np.quantile(bs, .025)), float(np.quantile(bs, .975))])


def share(x):
    x = np.asarray(x, float)
    return float(np.mean(x)) if len(x) else math.nan


def f(v, nd=1):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:.{nd}f}"


def pct(v):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{100 * v:.0f}%"


def pval(p):
    return "—" if p is None or (isinstance(p, float) and math.isnan(p)) else ("<0.001" if p < 0.001 else f"{p:.3f}")


def diff_cell(r, nd=1):
    return f"{f(r['median_diff'], nd)} [{f(r['ci95_median_diff'][0], nd)}, {f(r['ci95_median_diff'][1], nd)}] " \
           f"(p {pval(r['p_holm'])}; r={r['r_rb']:.2f})"


def clean_json(o):
    if isinstance(o, dict):
        return {str(k): clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_json(v) for v in o]
    if isinstance(o, (np.floating, float)):
        o = float(o)
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def prereg_check():
    txt = DOC.read_text(encoding="utf-8")
    pre = txt.split("<!-- PREREG:BEGIN -->")[1].split("<!-- PREREG:END -->")[0]
    h = hashlib.sha256(pre.encode("utf-8")).hexdigest()
    rec = (EXT / "prereg.sha256").read_text(encoding="utf-8").split()[0]
    return dict(sha256=h, recorded=rec, unchanged=h == rec)


# ------------------------------------------------------------------------------------------- Extension A
A_PRIMARY = "exposed_x_mean"
A_SECONDARY = ("during_x_mean", "after_x_mean", "blk_bcd", "exposed_x_never_extra")
A_DESC = ("exposed_x_mean", "before_x_mean", "during_x_mean", "after_x_mean", "exposed_x_never_extra",
          "exposed_never", "before_mean", "during_mean", "during_p95", "after_mean", "after_p95", "exposed_mean",
          "exposed_p95", "blk_bcd", "blk_displaced", "m_FRE_state", "m_T_conv", "burst_extra_never")
A_REPRO = ("T_det", "T_decl", "T_conv", "T_bk", "T_true", "FRE", "FRE_state", "FRE_backlog", "over_delay",
           "resid_at_decl", "residue_auc", "conf_lat_mean", "unconfirmed_post", "announced", "requested", "transfers")


def repro_check(df):
    """Every re-simulated held-out run must equal the stored main-study row (results/all_runs.csv)."""
    main = pd.read_csv(ROOT / "results" / "all_runs.csv")
    main = main[main.history == "disturbed"]
    mine = df[(df["sample"] == "heldout") & (df.history == "disturbed")]
    m = mine.merge(main, on=["seed", "dist", "policy"], how="left", suffixes=("", "_main"), indicator=True)
    out = dict(runs=int(len(mine)), found=int((m["_merge"] == "both").sum()), columns=list(A_REPRO), mismatches={})
    for c in A_REPRO:
        a = m[f"m_{c}"].astype(float).to_numpy()
        b = m[c].astype(float).to_numpy()
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        out["mismatches"][c] = int((~same).sum())
    out["all_identical"] = out["found"] == out["runs"] and not any(out["mismatches"].values())
    return out


def analyze_a(df):
    res = dict(reproduction=repro_check(df), samples={},
               runs={s: dict(disturbed=int(((df["sample"] == s) & (df.history == "disturbed")).sum()),
                             clean_histories=int(((df["sample"] == s) & (df.history == "clean")).sum() // 2))
                     for s in df["sample"].unique()})
    for sample in ("heldout", "replication"):
        d = df[df["sample"] == sample]
        if d.empty:
            continue
        dist_rows = d[d.history == "disturbed"]
        clean = d[d.history == "clean"]
        seeds = sorted(d.seed.unique())

        def cell(pol, dist, col):
            x = dist_rows[(dist_rows.policy == pol) & (dist_rows.dist == dist)].set_index("seed")[col]
            return x.reindex(seeds).astype(float)

        def pooled(pol, col):
            return dist_rows[dist_rows.policy == pol].groupby("seed")[col].mean().reindex(seeds).astype(float)

        desc = {dd: {p: {c: describe(cell(p, dd, c)) for c in A_DESC} for p in POL} for dd in DISTURBANCES}
        for dd in DISTURBANCES:
            for p in POL:
                x = cell(p, dd, A_PRIMARY)
                desc[dd][p]["primary_ci95_median"] = paired_test(x.values, np.zeros(len(x)))["ci95_median_diff"]
        clean_desc = {f"{te:g}": {c: describe(clean[clean.cutoff == te][c]) for c in
                                  ("exposed_mean", "exposed_p95", "during_mean", "after_mean", "exposed_never")}
                      for te in sorted(clean.cutoff.unique())}
        # A1: harm vs the clean history
        a1, fam = {}, []
        for dd in DISTURBANCES:
            a1[dd] = {}
            for p in POL:
                x = cell(p, dd, A_PRIMARY).values
                r = paired_test(x, np.zeros(len(x)))
                a1[dd][p] = r
                fam.append(r)
        holm(fam)
        # A2: policies, primary and secondary families
        a2 = {}
        for metric in (A_PRIMARY,) + A_SECONDARY:
            a2[metric], fam = {}, []
            for base in ("B1", "B2"):
                key = f"SARA_vs_{base}"
                a2[metric][key] = {}
                for dd in DISTURBANCES:
                    r = paired_test(cell("SARA", dd, metric).values, cell(base, dd, metric).values)
                    a2[metric][key][dd] = r
                    fam.append(r)
                r = paired_test(pooled("SARA", metric).values, pooled(base, metric).values)
                a2[metric][key]["pooled"] = r
                fam.append(r)
            holm(fam)
        # A3: association between false certification and harm
        a3 = {}
        for p in ("B1", "B2"):
            a3[p] = {}
            for dd in DISTURBANCES:
                x, y = cell(p, dd, "m_FRE_state").values, cell(p, dd, A_PRIMARY).values
                ok = np.isfinite(x) & np.isfinite(y)
                if ok.sum() > 2 and np.std(x[ok]) > 0 and np.std(y[ok]) > 0:
                    rho, pv = stats.spearmanr(x[ok], y[ok])
                    a3[p][dd] = dict(rho=float(rho), p=float(pv), n=int(ok.sum()))
                else:
                    a3[p][dd] = dict(rho=math.nan, p=math.nan, n=int(ok.sum()))
        key_q = {}
        for dd in list(DISTURBANCES) + ["pooled"]:
            key_q[dd] = {b: bool(a2[A_PRIMARY][f"SARA_vs_{b}"][dd]["median_diff"] < 0
                                 and a2[A_PRIMARY][f"SARA_vs_{b}"][dd]["p_holm"] < 0.05) for b in ("B1", "B2")}
        res["samples"][sample] = dict(n_seeds=len(seeds), seeds=[int(seeds[0]), int(seeds[-1])],
                                      descriptive=desc, clean=clean_desc, A1_harm_vs_clean=a1, A2_policies=a2,
                                      A3_spearman=a3, key_question=key_q)
    return res


# ------------------------------------------------------------------------------------------- Extension B
def analyze_b(df, meta):
    cal = df[df.variant == "calibrated"]
    rec = df[df.variant == "recalibrated"]
    # change log 13:12: the 50-node cells are analysed on partition only (their other rows are not analysed)
    cal = cal[(cal.history == "clean") | (cal.dist == "partition") | (cal.n_nodes < 50)]
    seeds = sorted(cal.seed.unique())
    order = sorted(meta["cells"], key=lambda c: (meta["cells"][c]["load"] != "scaled",
                                                 ("random_regular", "erdos_renyi", "watts_strogatz").index(
                                                     meta["cells"][c]["topology"]),
                                                 meta["cells"][c]["n_nodes"], meta["cells"][c]["degree"]))

    def ps(frame, p, col):
        return frame[frame.policy == p].groupby("seed")[col].mean().reindex(seeds).astype(float).values

    per_cell, fam_fre, fam_od, fam_other = {}, [], [], []
    for c in order:
        sub = cal[cal.cell == c]
        if sub.empty:
            continue
        part = sub[(sub.history == "disturbed") & (sub.dist == "partition")]
        other = sub[(sub.history == "disturbed") & (sub.dist.isin(["isolation", "asymmetric"]))]
        cs = sub[(sub.history == "clean") & (sub.policy == "SARA")]
        info = dict(meta["cells"][c])
        info.pop("overrides", None)
        r = dict(cell=info, n_seeds=int(sub.seed.nunique()),
                 graph=dict(diameter_mean=float(sub.diameter.mean()), mean_degree=float(sub.mean_degree.mean()),
                            max_degree_mean=float(sub.max_degree.mean())))
        b1 = part[part.policy == "B1"]
        r["B1_residue_auc_median"] = float(b1.residue_auc.median())
        r["B1_resid_10_median"] = float(b1.resid_10.median())
        for p in POL:
            q = part[part.policy == p]
            r[p] = dict(certified_with_residue=share(q.FRE_state > 0), FRE_state=boot_mean(q.FRE_state),
                        FRE=boot_mean(q.FRE), over_delay=boot_mean(q.over_delay), T_conv=boot_mean(q.T_conv),
                        declared_share=share(~q.decl_censored.astype(bool)))
        r["SARA_false_incidents"] = dict(mean=float(cs.incidents_after_warmup.mean()),
                                         share_any=share(cs.incidents_after_warmup > 0))
        t1 = paired_test(ps(part, "SARA", "FRE_state"), ps(part, "B1", "FRE_state"))
        t2 = paired_test(ps(part, "SARA", "FRE_state"), ps(part, "B2", "FRE_state"))
        t3 = paired_test(ps(part, "SARA", "over_delay"), ps(part, "B2", "over_delay"))
        r["SARA_vs_B1_FRE_state"], r["SARA_vs_B2_FRE_state"], r["SARA_vs_B2_over_delay"] = t1, t2, t3
        fam_fre += [t1, t2]
        fam_od.append(t3)
        if not other.empty:                       # 10- and 20-node cells: isolation and asymmetric
            o = {}
            for p in POL:
                q = other[other.policy == p]
                o[p] = dict(certified_with_residue=share(q.FRE_state > 0),
                            certified_with_residue_by_dist={x: share(q[q.dist == x].FRE_state > 0)
                                                            for x in ("isolation", "asymmetric")},
                            FRE_state=boot_mean(q.groupby("seed").FRE_state.mean()),
                            over_delay=boot_mean(q.groupby("seed").over_delay.mean()))
            u1 = paired_test(ps(other, "SARA", "FRE_state"), ps(other, "B1", "FRE_state"))
            u2 = paired_test(ps(other, "SARA", "FRE_state"), ps(other, "B2", "FRE_state"))
            o["SARA_vs_B1_FRE_state"], o["SARA_vs_B2_FRE_state"] = u1, u2
            fam_other += [u1, u2]
            r["isolation_asymmetric"] = o
        # secondary: re-calibrated SARA on the same seeds (partition)
        rs = rec[rec.cell == c]
        if not rs.empty:
            q = rs[(rs.history == "disturbed") & (rs.policy == "SARA") & (rs.dist == "partition")]
            qc = rs[(rs.history == "clean") & (rs.policy == "SARA")]
            r["SARA_recalibrated"] = dict(
                values=meta.get("recalibration", {}).get(c, {}).get("values"),
                certified_with_residue=share(q.FRE_state > 0), FRE_state=boot_mean(q.FRE_state),
                over_delay=boot_mean(q.over_delay),
                false_incidents=dict(mean=float(qc.incidents_after_warmup.mean()),
                                     share_any=share(qc.incidents_after_warmup > 0)))
        per_cell[c] = r
    holm(fam_fre)
    holm(fam_od)
    if fam_other:
        holm(fam_other)
    for c, r in per_cell.items():
        r["advantage_vs_B2"] = ("reverses" if r["SARA"]["FRE_state"]["mean"] > r["B2"]["FRE_state"]["mean"]
                                else "shrinks" if r["SARA_vs_B2_FRE_state"]["p_holm"] >= 0.05 else "holds")
        if "isolation_asymmetric" in r:
            o = r["isolation_asymmetric"]
            o["advantage_vs_B2"] = ("reverses" if o["SARA"]["FRE_state"]["mean"] > o["B2"]["FRE_state"]["mean"]
                                    else "shrinks" if o["SARA_vs_B2_FRE_state"]["p_holm"] >= 0.05 else "holds")
    hyp = dict(
        H_B1={c: bool(r["B1"]["certified_with_residue"] >= 0.9 and
                      ("isolation_asymmetric" not in r or
                       r["isolation_asymmetric"]["B1"]["certified_with_residue_by_dist"]["isolation"] >= 0.9))
              for c, r in per_cell.items()},
        H_B2={c: bool(r["SARA"]["FRE_state"]["mean"] < r["B1"]["FRE_state"]["mean"]
                      and r["SARA"]["FRE_state"]["mean"] < r["B2"]["FRE_state"]["mean"]) for c, r in per_cell.items()},
    )
    lines = {}
    for c, r in per_cell.items():
        ci = r["cell"]
        if ci["load"] == "scaled":
            lines.setdefault(f"{ci['topology']}_d{ci['degree']}", {})[ci["n_nodes"]] = dict(
                false_incidents=r["SARA_false_incidents"]["mean"], over_delay=r["SARA"]["over_delay"]["mean"])
    hyp["H_B3_by_line"] = {k: dict(false_incidents_up=v[50]["false_incidents"] > v[10]["false_incidents"],
                                   over_delay_up=v[50]["over_delay"] > v[10]["over_delay"])
                           for k, v in lines.items() if 10 in v and 50 in v}
    hyp["H_B4"] = {}
    for n in (20, 50):
        sc, fx = per_cell.get(f"random_regular_n{n}_d4_scaled"), per_cell.get(f"random_regular_n{n}_d4_fixed")
        if sc and fx:
            hyp["H_B4"][n] = dict(scaled=sc["B1_residue_auc_median"], fixed=fx["B1_residue_auc_median"],
                                  smaller_at_fixed=fx["B1_residue_auc_median"] < sc["B1_residue_auc_median"])
    runs = {v: dict(disturbed=int(((df.variant == v) & (df.history == "disturbed")).sum()),
                    clean=int(((df.variant == v) & (df.history == "clean")).sum())) for v in df.variant.unique()}
    return dict(order=order, cells=per_cell, hypotheses=hyp, dists=meta["dists"], seeds=meta["seeds"],
                main_cell=meta["main_cell"], runs=runs)


# ------------------------------------------------------------------------------------------- Extension C
LEVELS = ("none", "loose", "mid", "tight")


def analyze_c(df, cal):
    out = dict(caps=cal["caps"], M=cal["M"], clean={}, disturbed={}, paired={},
               runs={lv: dict(disturbed=int(((df.cap_level == lv) & (df.history == "disturbed")).sum()),
                              clean=int(((df.cap_level == lv) & (df.history == "clean")).sum() // 2))
                     for lv in LEVELS if (df.cap_level == lv).any()})
    clean = df[(df.history == "clean") & (df.cutoff == df.cutoff.max())]
    for lv in LEVELS:
        c = clean[clean.cap_level == lv]
        if c.empty:
            continue
        drops = (c.evicted > 0) | (c.rejected > 0)
        cs = c[c.policy == "SARA"]
        out["clean"][lv] = dict(
            runs=int(len(c)), share_with_drops=share(drops), evicted_mean=float(c.evicted.mean()),
            rejected_mean=float(c.rejected.mean()),
            runs_without_drops=int((~drops).sum()),
            runs_without_drops_checked_zero=int(c.clean_no_drops_checked.astype(bool).sum()),
            share_residue=share(c.res_max > 0), share_evdiv=share(c.evdiv_max > 0),
            SARA_false_incidents=dict(mean=float(cs.incidents_after_warmup.mean()),
                                      share_any=share(cs.incidents_after_warmup > 0)))
    d = df[df.history == "disturbed"]
    fam = []
    for lv in LEVELS:
        seeds = sorted(d[d.cap_level == lv].seed.unique())
        if not seeds:
            continue
        out["disturbed"][lv], out["paired"][lv] = {}, {}
        for dist in DISTURBANCES:
            out["disturbed"][lv][dist] = {}
            for p in POL:
                q = d[(d.cap_level == lv) & (d.dist == dist) & (d.policy == p)]
                if q.empty:
                    continue
                g = lambda col: float(q[col].mean()) if col in q and q[col].notna().any() else math.nan  # noqa: E731
                e = dict(runs=int(len(q)), evicted=g("evicted"), rejected=g("rejected"),
                         evdiv_10=g("evdiv_10"), evdiv_60=g("evdiv_60"), evdiv_300=g("evdiv_300"),
                         share_evdiv_300=share(q.evdiv_300 > 0) if "evdiv_300" in q and q.evdiv_300.notna().any() else math.nan,
                         evdiv_end=g("evdiv_end"), evdiv_auc=g("evdiv_auc"),
                         evconv_censored=share(q.evconv_censored.astype(float)) if "evconv_censored" in q and q.evconv_censored.notna().any() else math.nan,
                         gres_10=g("gres_10"), lost_end=g("lost_end"), U_300=g("U_300"),
                         FRE_state=boot_mean(q.FRE_state), certified_with_residue=share(q.FRE_state > 0),
                         declared_share=share(~q.decl_censored.astype(bool)), over_delay=g("over_delay"),
                         T_conv=g("T_conv"), conv_censored=share(q.conv_censored.astype(float)))
                if p == "SARA":
                    e.update(state_alarm=share(q.state_alarm.astype(float)), unrepairable=g("unrepairable"),
                             reached_high=share(q.max_tier_post >= 2), reached_critical=share(q.max_tier_post >= 3),
                             share_high_post=g("share_high_post"))
                out["disturbed"][lv][dist][p] = e

            def cellv(p):
                return d[(d.cap_level == lv) & (d.dist == dist) & (d.policy == p)].set_index("seed").FRE_state \
                    .reindex(seeds).astype(float).values
            out["paired"][lv][dist] = {}
            for b in ("B1", "B2"):
                r = paired_test(cellv("SARA"), cellv(b))
                out["paired"][lv][dist][f"SARA_vs_{b}"] = r
                fam.append(r)
    holm(fam)
    return out


# ------------------------------------------------------------------------------------------- figures
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "legend.fontsize": 7,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "font.family": "DejaVu Sans",
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    return plt


def _save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.png", dpi=200, bbox_inches="tight")
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")


def fig_a(a):
    plt = _plt()
    s = a["samples"]["heldout"]
    fig, ax = plt.subplots(figsize=(7.16, 2.6))
    x = np.arange(len(DISTURBANCES))
    w = 0.26
    top, bottom = 1.0, 0.0
    for k, p in enumerate(POL):
        med = [s["descriptive"][dd][p][A_PRIMARY]["median"] for dd in DISTURBANCES]
        ci = np.array([s["descriptive"][dd][p]["primary_ci95_median"] for dd in DISTURBANCES], float)
        top, bottom = max(top, np.nanmax(ci[:, 1])), min(bottom, np.nanmin(ci[:, 0]))
        xs = x + (k - 1) * w
        ax.errorbar(xs, med, yerr=[np.array(med) - ci[:, 0], ci[:, 1] - np.array(med)], fmt="o", ms=4,
                    color=PCOL[p], lw=0.9, capsize=2, label=p)
    ax.axhline(0, color="#c3c2b7", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([LAB[dd] for dd in DISTURBANCES], rotation=15)
    ax.set_yscale("symlog", linthresh=1)
    ax.set_ylim(min(-0.2, bottom * 1.5), top * 2.5)
    ax.set_ylabel("excess confirmation delay (s)\nmedian over runs, 95% CI")
    ax.set_title("Extension A: per-run mean excess delay of the exposed workload, disturbed minus clean "
                 "(held-out seeds 1000–1199)")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    fig.tight_layout()
    _save(fig, "ext_a_excess_delay")
    plt.close(fig)


def fig_b(b):
    plt = _plt()
    cells = b["cells"]
    topos = ("random_regular", "erdos_renyi", "watts_strogatz")
    fig, axes = plt.subplots(2, 3, figsize=(7.16, 3.6), sharex=True)
    for col, topo in enumerate(topos):
        for row, deg in enumerate((4, 8)):
            ax = axes[row, col]
            for p in POL:
                xs, ms, lo, hi = [], [], [], []
                for n in (10, 20, 50):
                    r = cells.get(f"{topo}_n{n}_d{deg}_scaled")
                    if r:
                        xs.append({10: 0, 20: 1, 50: 2}[n])
                        ms.append(r[p]["FRE_state"]["mean"])
                        lo.append(r[p]["FRE_state"]["ci95"][0])
                        hi.append(r[p]["FRE_state"]["ci95"][1])
                ax.plot(xs, ms, marker="o", ms=3, color=PCOL[p], lw=1, label=p)
                ax.fill_between(xs, lo, hi, color=PCOL[p], alpha=0.15, lw=0)
            ax.set_yscale("symlog", linthresh=1)
            ax.set_xticks([0, 1, 2])
            ax.set_xticklabels(["10", "20", "50"])
            ax.set_title(f"{topo.replace('_', ' ')}, degree {deg}")
            if col == 0:
                ax.set_ylabel("FRE_state, mean (s)")
            if row == 1:
                ax.set_xlabel("nodes")
    axes[0, 0].legend(frameon=False, fontsize=6.5)
    fig.suptitle("Extension B: FRE_state after a partition, mean with 95% CI per cell (rate scaled with n; "
                 "calibrated SARA)", fontsize=8)
    fig.tight_layout()
    _save(fig, "ext_b_fre_state")
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 2.4))
    styles = {"random_regular": "-", "erdos_renyi": "--", "watts_strogatz": ":"}
    for topo in topos:
        for deg, mk in ((4, "o"), (8, "s")):
            xs, fi, od = [], [], []
            for n in (10, 20, 50):
                r = cells.get(f"{topo}_n{n}_d{deg}_scaled")
                if r:
                    xs.append({10: 0, 20: 1, 50: 2}[n])
                    fi.append(r["SARA_false_incidents"]["mean"])
                    od.append(r["SARA"]["over_delay"]["mean"])
            lab = f"{topo.replace('_', ' ')}, d={deg}"
            axes[0].plot(xs, fi, ls=styles[topo], marker=mk, ms=3, color=PCOL["SARA"], lw=1, label=lab)
            axes[1].plot(xs, od, ls=styles[topo], marker=mk, ms=3, color=PCOL["SARA"], lw=1, label=lab)
    for ax, yl in zip(axes, ("false incidents per clean run", "over-delay, mean (s)")):
        ax.set_xticks([0, 1, 2])
        ax.set_xticklabels(["10", "20", "50"])
        ax.set_xlabel("nodes")
        ax.set_ylabel(yl)
        ax.set_ylim(bottom=0)
    axes[1].legend(frameon=False, fontsize=6, loc="upper left")
    fig.suptitle("Extension B: SARA's costs per cell (calibrated values from the 10-node network; over-delay after "
                 "a partition)", fontsize=8)
    fig.tight_layout()
    _save(fig, "ext_b_sara_costs")
    plt.close(fig)


def fig_c(c):
    plt = _plt()
    levels = [lv for lv in LEVELS if lv in c["disturbed"] and c["disturbed"][lv]]
    xl = [f"{lv}\n({'∞' if lv == 'none' else c['caps'][lv]})" for lv in levels]
    fig, axes = plt.subplots(1, 3, figsize=(7.16, 2.4))
    def avg(v):
        v = np.asarray(v, float)
        return float(np.mean(v[np.isfinite(v)])) if np.isfinite(v).any() else math.nan   # "none" has no EvDiv

    for p in POL:
        fre = [avg([c["disturbed"][lv][dd][p]["FRE_state"]["mean"] for dd in DISTURBANCES]) for lv in levels]
        dec = [avg([c["disturbed"][lv][dd][p]["declared_share"] for dd in DISTURBANCES]) for lv in levels]
        ev = [avg([c["disturbed"][lv][dd][p]["evdiv_60"] for dd in DISTURBANCES]) for lv in levels]
        axes[0].plot(range(len(levels)), fre, marker="o", ms=3, color=PCOL[p], lw=1, label=p)
        axes[1].plot(range(len(levels)), dec, marker="o", ms=3, color=PCOL[p], lw=1, label=p)
        axes[2].plot(range(len(levels)), ev, marker="o", ms=3, color=PCOL[p], lw=1, label=p)
    for ax, yl in zip(axes, ("FRE_state, mean (s)", "runs declared recovered\nbefore the horizon (share)",
                             "evicted-divergence at\nt_end + 60 s (tx, mean)")):
        ax.set_xticks(range(len(levels)))
        ax.set_xticklabels(xl)
        ax.set_xlabel("mempool cap (tx per node)")
        ax.set_ylabel(yl)
        ax.set_ylim(bottom=0)
    axes[0].legend(frameon=False)
    fig.suptitle("Extension C: bounded mempools, mean over the six disturbance types (seeds 3000–3099)", fontsize=8)
    fig.tight_layout()
    _save(fig, "ext_c_capacity")
    plt.close(fig)


# ------------------------------------------------------------------------------------------- report
def report_a(a, w):
    rp = a["reproduction"]
    w("### Extension A: confirmation delay and block composition\n")
    w("Runs: " + "; ".join(f"{s}: {v['disturbed']} disturbed runs (B1/B2/SARA × six disturbances) and "
                           f"{v['clean_histories']} clean histories" for s, v in a["runs"].items()) + ".\n")
    w(f"Reproduction check: {rp['found']} of {rp['runs']} re-simulated held-out runs matched to stored rows of "
      f"`results/all_runs.csv`; mismatching values per column: "
      + ", ".join(f"{k} {v}" for k, v in rp["mismatches"].items())
      + f". All identical: **{rp['all_identical']}**.\n")
    for sample, s in a["samples"].items():
        title = ("held-out seeds 1000–1199 (the main study's runs)" if sample == "heldout"
                 else "replication seeds 3000–3099")
        w(f"#### A1, A2: {title}\n")
        w("Primary outcome = per-run mean excess confirmation delay of shared-workload transactions created in "
          "[180 s, t_end + 300 s), disturbed minus paired clean history (s; unconfirmed censored at the horizon, so "
          "a lower bound). A1 tests it against 0 (Holm over 18); A2 compares SARA with each baseline (Holm over 14). "
          "Cells: median [95% CI of the median] (Holm p; r).\n")
        w("| Disturbance | B1 vs clean | B2 vs clean | SARA vs clean | SARA − B1 | SARA − B2 | users worse off under the falsely certifying baseline? |")
        w("| --- | --- | --- | --- | --- | --- | --- |")
        for dd in list(DISTURBANCES) + ["pooled"]:
            cells = []
            for p in POL:
                if dd == "pooled":
                    cells.append("")
                else:
                    r = s["A1_harm_vs_clean"][dd][p]
                    cells.append(diff_cell(r, 2))
            x1 = s["A2_policies"][A_PRIMARY]["SARA_vs_B1"][dd]
            x2 = s["A2_policies"][A_PRIMARY]["SARA_vs_B2"][dd]
            kq = s["key_question"][dd]
            ans = f"vs B1: {'yes' if kq['B1'] else 'no'}; vs B2: {'yes' if kq['B2'] else 'no'}"
            w(f"| {LAB.get(dd, 'Pooled (per-seed mean)')} | " + " | ".join(cells) + f" | {diff_cell(x1, 2)} | "
              f"{diff_cell(x2, 2)} | {ans} |")
        w("")
        w("Secondary outcomes, medians per run (B1 / B2 / SARA): excess delay by creation window, never-confirmed "
          "extra transactions (exposed window), block-composition distance of blocks mined in [t_end, t_end + 300 s), "
          "and the run's FRE_state.\n")
        w("| Disturbance | before (s) | during (s) | after (s) | never-confirmed extra | BCD | FRE_state (s) |")
        w("| --- | --- | --- | --- | --- | --- | --- |")
        for dd in DISTURBANCES:
            def trio(col, nd=2):
                return " / ".join(f(s["descriptive"][dd][p][col].get("median"), nd) for p in POL)
            w(f"| {LAB[dd]} | {trio('before_x_mean')} | {trio('during_x_mean')} | {trio('after_x_mean')} | "
              f"{trio('exposed_x_never_extra', 0)} | {trio('blk_bcd', 3)} | {trio('m_FRE_state', 0)} |")
        w("")
        w("SARA minus baseline on the secondary outcomes (median paired difference, Holm p within each outcome):\n")
        w("| Disturbance | during: vs B1 | during: vs B2 | after: vs B1 | after: vs B2 | BCD: vs B1 | BCD: vs B2 | never-conf. extra: vs B1 | vs B2 |")
        w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for dd in list(DISTURBANCES) + ["pooled"]:
            cells = []
            for metric, nd in (("during_x_mean", 2), ("after_x_mean", 2), ("blk_bcd", 3), ("exposed_x_never_extra", 1)):
                for b in ("B1", "B2"):
                    r = s["A2_policies"][metric][f"SARA_vs_{b}"][dd]
                    cells.append(f"{f(r['median_diff'], nd)} ({pval(r['p_holm'])})")
            w(f"| {LAB.get(dd, 'Pooled')} | " + " | ".join(cells) + " |")
        w("")
        w("A3: Spearman ρ between FRE_state and the primary outcome across runs (unadjusted p):\n")
        w("| Disturbance | B1 ρ (p) | B2 ρ (p) |")
        w("| --- | --- | --- |")
        for dd in DISTURBANCES:
            cells = [f"{f(s['A3_spearman'][p][dd]['rho'], 2)} ({pval(s['A3_spearman'][p][dd]['p'])})" for p in ("B1", "B2")]
            w(f"| {LAB[dd]} | " + " | ".join(cells) + " |")
        cl = s["clean"]
        w("\nClean-history reference (median per run): exposed-window mean delay "
          + "; ".join(f"t_end {k} s: {f(v['exposed_mean']['median'], 1)} s (p95 {f(v['exposed_p95']['median'], 1)} s, "
                      f"never confirmed {f(v['exposed_never']['median'], 0)})" for k, v in cl.items()) + ".\n")
    w("![Extension A: excess confirmation delay](figures/ext_a_excess_delay.png)\n")


def both_zero(r):
    return " (both 0)" if r["SARA"]["FRE_state"]["mean"] == 0 and r["B2"]["FRE_state"]["mean"] == 0 else ""


def report_b(b, w):
    w("### Extension B: scale and topology\n")
    w("Runs: " + "; ".join(f"{v}: {x['disturbed']} disturbed and {x['clean']} clean" for v, x in b["runs"].items())
      + f" (plus, per job, one clean B1 history as the backlog counterfactual of the re-calibrated runs).\n")
    w(f"Seeds {b['seeds'][0]}–{b['seeds'][-1]} per cell; calibrated SARA values fixed. Following the scope change "
      "in the change log, the cross-cell table uses the partition runs, which exist in every cell. SARA − B2: median "
      "paired difference of FRE_state, Holm over all cells and both comparisons. Advantage vs B2: *holds* (Holm p < "
      "0.05), *shrinks* (not significant), *reverses* (SARA's mean higher). False incidents come from the clean SARA "
      "histories.\n")

    def name(c, r):
        ci = r["cell"]
        return (f"{ci['topology'].replace('_', ' ')}, n={ci['n_nodes']}, d={ci['degree']}, {ci['load']}"
                + (" (main config.)" if c == b["main_cell"] else ""))
    w("**Partition, every cell:**\n")
    w("| Cell | diameter | B1 residue AUC, median | certified with residue B1 / B2 / SARA | FRE_state mean B1 / B2 / SARA (s) | SARA − B2 FRE_state (Holm p) | advantage vs B2 | SARA over-delay (s) | SARA false incidents per clean run (share with any) |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in b["order"]:
        r = b["cells"].get(c)
        if not r:
            continue
        t2 = r["SARA_vs_B2_FRE_state"]
        w(f"| {name(c, r)} | {f(r['graph']['diameter_mean'], 1)} | {f(r['B1_residue_auc_median'], 0)} | "
          + " / ".join(pct(r[p]["certified_with_residue"]) for p in POL) + " | "
          + " / ".join(f(r[p]["FRE_state"]["mean"]) for p in POL) + f" | {f(t2['median_diff'])} ({pval(t2['p_holm'])}) | "
          f"{r['advantage_vs_B2']}{both_zero(r)} | {f(r['SARA']['over_delay']['mean'])} | "
          f"{f(r['SARA_false_incidents']['mean'], 2)} ({pct(r['SARA_false_incidents']['share_any'])}) |")
    w("")
    w("**Isolation and asymmetric link, 10- and 20-node cells** (FRE_state: mean of per-seed means over the two "
      "disturbances; own Holm family):\n")
    w("| Cell | certified with residue, isolation B1 / B2 / SARA | certified with residue, asymmetric B1 / B2 / SARA | FRE_state mean B1 / B2 / SARA (s) | SARA − B2 FRE_state (Holm p) | advantage vs B2 | SARA over-delay (s) |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for c in b["order"]:
        r = b["cells"].get(c)
        if not r or "isolation_asymmetric" not in r:
            continue
        o = r["isolation_asymmetric"]
        t2 = o["SARA_vs_B2_FRE_state"]
        w(f"| {name(c, r)} | "
          + " / ".join(pct(o[p]["certified_with_residue_by_dist"]["isolation"]) for p in POL) + " | "
          + " / ".join(pct(o[p]["certified_with_residue_by_dist"]["asymmetric"]) for p in POL) + " | "
          + " / ".join(f(o[p]["FRE_state"]["mean"]) for p in POL)
          + f" | {f(t2['median_diff'])} ({pval(t2['p_holm'])}) | {o['advantage_vs_B2']}{both_zero(o)} | "
            f"{f(o['SARA']['over_delay']['mean'])} |")
    w("")
    if any("SARA_recalibrated" in r for r in b["cells"].values()):
        w("**Secondary, re-calibrated SARA** (re-calibrated on dev seeds 0–4 for the cell; partition; same seeds):\n")
        w("| Cell | tau_m (s) | beta (blocks) | certified with residue | FRE_state mean (s) | over-delay (s) | false incidents per clean run (share with any) |")
        w("| --- | --- | --- | --- | --- | --- | --- |")
        for c in b["order"]:
            r = b["cells"].get(c)
            if not r or "SARA_recalibrated" not in r:
                continue
            x = r["SARA_recalibrated"]
            v = x["values"] or {}
            ci = r["cell"]
            w(f"| {ci['topology'].replace('_', ' ')}, n={ci['n_nodes']}, d={ci['degree']}, {ci['load']} | "
              f"{f(v.get('tau_m'), 2)} | {f(v.get('beta'), 2)} | {pct(x['certified_with_residue'])} | "
              f"{f(x['FRE_state']['mean'])} | {f(x['over_delay']['mean'])} | {f(x['false_incidents']['mean'], 2)} "
              f"({pct(x['false_incidents']['share_any'])}) |")
        w("")
    h = b["hypotheses"]
    nb1 = sum(h["H_B1"].values())
    nb2 = sum(h["H_B2"].values())
    w(f"Hypotheses: H-B1 (B1 certifies with residue in ≥ 90% of partition runs, and of isolation runs where run) "
      f"holds in {nb1} of "
      f"{len(h['H_B1'])} cells; H-B2 (SARA's mean FRE_state strictly below B1's and B2's after a partition; a cell "
      f"where SARA and B2 are both 0 does not count) holds in {nb2} of {len(h['H_B2'])} "
      "cells; H-B3 (SARA's false incidents / over-delay higher at n = 50 than at n = 10, per topology and degree): "
      + "; ".join(f"{k}: {'up' if v['false_incidents_up'] else 'not up'} / {'up' if v['over_delay_up'] else 'not up'}"
                  for k, v in h["H_B3_by_line"].items())
      + "; H-B4 (residue smaller at fixed total rate): "
      + "; ".join(f"n={n}: B1 residue AUC median {f(v['fixed'], 0)} fixed vs {f(v['scaled'], 0)} scaled "
                  f"({'smaller' if v['smaller_at_fixed'] else 'not smaller'})" for n, v in h["H_B4"].items()) + ".\n")
    w("![Extension B: FRE_state per cell](figures/ext_b_fre_state.png)\n")
    w("![Extension B: SARA's costs per cell](figures/ext_b_sara_costs.png)\n")


def report_c(c, w):
    w("### Extension C: bounded mempools and eviction\n")
    w(f"Caps from dev seeds 0–4 (M = {c['M']}): loose {c['caps']['loose']}, mid {c['caps']['mid']}, tight "
      f"{c['caps']['tight']} transactions per node; 'none' = unlimited (main configuration) on the same seeds "
      "3000–3099. Runs: " + "; ".join(f"{lv}: {x['disturbed']} disturbed and {x['clean']} clean"
                                      for lv, x in c["runs"].items()) + ".\n")
    w("Clean histories (B1 and SARA, 100 seeds each):\n")
    w("| Cap | runs with any eviction or rejection | evictions per run | runs without drops (all checked: zero residue and EvDiv) | runs with residue > 0 | runs with EvDiv > 0 | SARA false incidents per clean run (share with any) |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for lv, x in c["clean"].items():
        w(f"| {lv} | {pct(x['share_with_drops'])} | {f(x['evicted_mean'], 1)} | {x['runs_without_drops']} "
          f"({x['runs_without_drops_checked_zero']} checked) | {pct(x['share_residue'])} | {pct(x['share_evdiv'])} | "
          f"{f(x['SARA_false_incidents']['mean'], 2)} ({pct(x['SARA_false_incidents']['share_any'])}) |")
    w("")
    w("Disturbed runs. EvDiv = evicted-divergence (residue candidates some node lacks because it evicted or rejected "
      "them), means per run; FRE_state under the unchanged residue definition; declared = recovery declared before "
      "the horizon.\n")
    w("| Cap | Disturbance | evictions (B1 run) | EvDiv +10 s / +60 s / +300 s (B1) | runs with EvDiv > 0 at +300 s B1 / B2 / SARA | lost tx at horizon (B1) | FRE_state mean B1 / B2 / SARA (s) | declared B1 / B2 / SARA | SARA: alarm / unrepairable gaps / reached HIGH | SARA over-delay (s) |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for lv in LEVELS:
        for dd in DISTURBANCES:
            e = c["disturbed"].get(lv, {}).get(dd)
            if not e or "B1" not in e:
                continue
            b1, s = e["B1"], e["SARA"]
            w(f"| {lv if dd == 'partition' else ''} | {LAB[dd]} | {f(b1['evicted'], 0)} | "
              f"{f(b1['evdiv_10'])} / {f(b1['evdiv_60'])} / {f(b1['evdiv_300'])} | "
              + " / ".join(pct(e[p]["share_evdiv_300"]) for p in POL) + f" | {f(b1['lost_end'], 0)} | "
              + " / ".join(f(e[p]["FRE_state"]["mean"]) for p in POL) + " | "
              + " / ".join(pct(e[p]["declared_share"]) for p in POL)
              + f" | {pct(s['state_alarm'])} / {f(s['unrepairable'], 0)} / {pct(s['reached_high'])} | "
                f"{f(s['over_delay'])} |")
    w("")
    w("SARA minus baseline on FRE_state (median paired difference; Holm p over all caps, disturbances and both "
      "baselines):\n")
    w("| Cap | " + " | ".join(LAB[dd] for dd in DISTURBANCES) + " |")
    w("| --- | " + " | ".join("---" for _ in DISTURBANCES) + " |")
    for lv in LEVELS:
        if lv not in c["paired"]:
            continue
        cells = []
        for dd in DISTURBANCES:
            r1, r2 = c["paired"][lv][dd]["SARA_vs_B1"], c["paired"][lv][dd]["SARA_vs_B2"]
            cells.append(f"vs B1 {f(r1['median_diff'])} ({pval(r1['p_holm'])}); vs B2 {f(r2['median_diff'])} "
                         f"({pval(r2['p_holm'])})")
        w(f"| {lv} | " + " | ".join(cells) + " |")
    w("")
    capped = [lv for lv in ("loose", "mid", "tight") if lv in c["disturbed"]]
    cl = c["clean"]
    d = c["disturbed"]
    ev300 = lambda lv, dd, p: pct(d[lv][dd][p]["share_evdiv_300"])  # noqa: E731
    w("Hypotheses (evidence generated from the tables above):\n")
    if "loose" in cl:
        x = cl["loose"]
        w(f"- H-C1: at the loose cap {pct(x['share_with_drops'])} of clean runs evicted or rejected something "
          f"({'holds' if x['share_with_drops'] == 0 else 'holds only in part: the dev-seed maximum is exceeded on some extension seeds'}); "
          f"every clean run without drops at every cap showed zero residue and zero EvDiv: "
          f"{all(v['runs_without_drops'] == v['runs_without_drops_checked_zero'] for v in cl.values())}.")
    w("- H-C2: runs with EvDiv > 0 at t_end + 300 s under B1, " + "; ".join(
        f"{lv}: burst {ev300(lv, 'burst', 'B1')}, partition {ev300(lv, 'partition', 'B1')}, asymmetric "
        f"{ev300(lv, 'asymmetric', 'B1')}" for lv in capped) + ".")
    w("- H-C3: the same share under B1 / B2 / SARA, " + "; ".join(
        f"{lv}: burst {ev300(lv, 'burst', 'B1')} / {ev300(lv, 'burst', 'B2')} / {ev300(lv, 'burst', 'SARA')}, partition "
        f"{ev300(lv, 'partition', 'B1')} / {ev300(lv, 'partition', 'B2')} / {ev300(lv, 'partition', 'SARA')}"
        for lv in capped) + ".")
    if capped:
        sf = [d[lv][dd]["SARA"]["FRE_state"]["mean"] for lv in capped for dd in DISTURBANCES]
        sd = [d[lv][dd]["SARA"]["declared_share"] for lv in capped for dd in DISTURBANCES]
        sh = [d[lv][dd]["SARA"]["reached_high"] for lv in capped for dd in DISTURBANCES if dd != "loss"]
        bf = [d[lv][dd][p]["FRE_state"]["mean"] for lv in capped for dd in ("burst", "partition", "asymmetric")
              for p in ("B1", "B2")]
        bd = [d[lv][dd][p]["declared_share"] for lv in capped for dd in DISTURBANCES for p in ("B1", "B2")]
        w(f"- H-C4: at the capped levels SARA's mean FRE_state per disturbance is {f(min(sf))}–{f(max(sf))} s, it "
          f"declares recovery before the horizon in {pct(min(sd))}–{pct(max(sd))} of runs and reaches HIGH after "
          f"t_end in {pct(min(sh))}–{pct(max(sh))} of runs (packet loss excluded; its alarm share is in the table); "
          f"B1 and B2 declare in {pct(min(bd))}–{pct(max(bd))} of runs, with mean FRE_state {f(min(bf))}–{f(max(bf))} s "
          f"for burst, partition and asymmetric.")
    w("- H-C5: SARA false incidents per clean run, " + ", ".join(
        f"{lv} {f(cl[lv]['SARA_false_incidents']['mean'], 2)}" for lv in LEVELS if lv in cl) + ".\n")
    w("![Extension C: bounded mempools](figures/ext_c_capacity.png)\n")


def findings_a(a):
    s = a["samples"]["heldout"]
    d, a2 = s["descriptive"], s["A2_policies"]
    out = []
    for dd in ("partition", "isolation"):
        r = a2[A_PRIMARY]["SARA_vs_B1"][dd]
        out.append(f"{LAB[dd]}: per-run mean excess delay of the exposed workload, median {f(d[dd]['B1'][A_PRIMARY]['median'], 2)} s "
                   f"under B1 vs {f(d[dd]['SARA'][A_PRIMARY]['median'], 2)} s under SARA and "
                   f"{f(d[dd]['B2'][A_PRIMARY]['median'], 2)} s under B2 (SARA − B1 median paired difference "
                   f"{f(r['median_diff'], 2)} s, Holm p {pval(r['p_holm'])}); transactions created during the "
                   f"disturbance: {f(d[dd]['B1']['during_x_mean']['median'], 1)} s (B1) vs "
                   f"{f(d[dd]['SARA']['during_x_mean']['median'], 1)} s (SARA).")
    yes1 = [LAB.get(x, "pooled") for x, v in s["key_question"].items() if v["B1"]]
    yes2 = [LAB.get(x, "pooled") for x, v in s["key_question"].items() if v["B2"]]
    out.append(f"Users worse off under the falsely certifying baseline (pre-registered criterion): vs B1 in "
               f"{', '.join(yes1) or 'none'}; vs B2 in {', '.join(yes2) or 'none'}.")
    r = a2["after_x_mean"]["SARA_vs_B1"]["partition"]
    out.append(f"Unfavourable to SARA: transactions created after a partition ended waited slightly longer under SARA "
               f"than under B1 (SARA − B1 median paired difference of the after-window excess "
               f"{f(r['median_diff'], 2)} s, Holm p {pval(r['p_holm'])}).")
    out.append(f"Burst: the largest excess delay, the same under every policy (median "
               f"{f(d['burst']['B1'][A_PRIMARY]['median'], 2)} s; on average "
               f"{f(d['burst']['B1']['exposed_x_never_extra']['mean'], 1)} exposed-window shared-workload transactions per "
               f"run confirmed in the clean history but not by the horizon, plus "
               f"{f(d['burst']['B1']['burst_extra_never']['mean'], 1)} burst transactions never confirmed).")
    sp = s["A3_spearman"]["B1"]
    out.append(f"Within B1, Spearman ρ between FRE_state and the primary outcome: partition "
               f"{f(sp['partition']['rho'], 2)}, isolation {f(sp['isolation']['rho'], 2)}.")
    rep = a["samples"].get("replication")
    if rep:
        same = all(rep["key_question"][x] == s["key_question"][x] for x in s["key_question"])
        out.append(f"Replication on seeds 3000–3099 gives the same yes/no answers for every disturbance: {same}.")
    return out


def findings_b(b):
    cells = b["cells"]
    out = []
    adv = {k: [c for c, r in cells.items() if r["advantage_vs_B2"] == k] for k in ("holds", "shrinks", "reverses")}
    out.append(f"Partition: SARA's FRE_state advantage over B2 holds in {len(adv['holds'])} of {len(cells)} cells, "
               f"shrinks (not significant after Holm) in {len(adv['shrinks'])}"
               + (f" ({', '.join(adv['shrinks'])})" if adv["shrinks"] else "")
               + f", reverses in {len(adv['reverses'])}" + (f" ({', '.join(adv['reverses'])})" if adv["reverses"] else "") + ".")
    oth = {c: r["isolation_asymmetric"] for c, r in cells.items() if "isolation_asymmetric" in r}
    if oth:
        ao = {k: [c for c, o in oth.items() if o["advantage_vs_B2"] == k] for k in ("holds", "shrinks", "reverses")}
        out.append(f"Isolation and asymmetric link (10- and 20-node cells): advantage over B2 holds in {len(ao['holds'])} "
                   f"of {len(oth)} cells, shrinks in {len(ao['shrinks'])}"
                   + (f" ({', '.join(ao['shrinks'])})" if ao["shrinks"] else "")
                   + f", reverses in {len(ao['reverses'])}" + (f" ({', '.join(ao['reverses'])})" if ao["reverses"] else "")
                   + f"; SARA certified with residue in at most "
                   f"{pct(max(o['SARA']['certified_with_residue'] for o in oth.values()))} of a cell's runs.")
    cw = {c: r["SARA"]["certified_with_residue"] for c, r in cells.items()}
    worst = max(cw, key=cw.get)
    out.append(f"Partition: SARA certified recovery while residue remained in at most {pct(cw[worst])} of a cell's runs "
               f"({worst}); B1 in {pct(min(r['B1']['certified_with_residue'] for r in cells.values()))}–"
               f"{pct(max(r['B1']['certified_with_residue'] for r in cells.values()))}; B2 in "
               f"{pct(min(r['B2']['certified_with_residue'] for r in cells.values()))}–"
               f"{pct(max(r['B2']['certified_with_residue'] for r in cells.values()))}.")
    fi = {c: r["SARA_false_incidents"]["mean"] for c, r in cells.items()}
    od = {c: r["SARA"]["over_delay"]["mean"] for c, r in cells.items()}
    hi_fi, hi_od = max(fi, key=fi.get), max(od, key=od.get)
    out.append(f"SARA's costs: false incidents per clean run from {f(min(fi.values()), 2)} to {f(fi[hi_fi], 2)} "
               f"({hi_fi}); over-delay after a partition from {f(min(od.values()))} s to {f(od[hi_od])} s ({hi_od})."
               + (f" Main configuration: {f(fi[b['main_cell']], 2)} false incidents per clean run, "
                  f"{f(od[b['main_cell']])} s over-delay." if b["main_cell"] in fi else ""))
    both0 = [c for c, r in cells.items() if r["SARA"]["FRE_state"]["mean"] == 0 and r["B2"]["FRE_state"]["mean"] == 0]
    if both0:
        out.append(f"In {len(both0)} cells SARA and B2 both have zero FRE_state after a partition, so 'shrinks' there "
                   f"means there was no advantage left to show, not that SARA did worse.")
    rec = {c: r["SARA_recalibrated"] for c, r in cells.items() if "SARA_recalibrated" in r}
    if rec:
        parts = []
        for c, x in rec.items():
            r, v = cells[c], x.get("values") or {}
            parts.append(f"{c}: false incidents per clean run {f(r['SARA_false_incidents']['mean'], 2)} → "
                         f"{f(x['false_incidents']['mean'], 2)}, partition runs certified with residue "
                         f"{pct(r['SARA']['certified_with_residue'])} → {pct(x['certified_with_residue'])} (mean "
                         f"FRE_state {f(r['SARA']['FRE_state']['mean'])} → {f(x['FRE_state']['mean'])} s; re-calibrated "
                         f"tau_m {f(v.get('tau_m'), 2)} s, eps_D {v.get('eps_D', math.nan):.4f})")
        out.append("Secondary, SARA re-calibrated with the Phase 3 rule on dev seeds (calibrated → re-calibrated): "
                   + "; ".join(parts) + ".")
    return out


def findings_c(c):
    out = []
    cl = c["clean"]
    if "loose" in cl:
        x = cl["loose"]
        out.append(f"Loose cap ({c['caps']['loose']}): {pct(x['share_with_drops'])} of clean runs evicted or rejected "
                   f"anything; all {x['runs_without_drops']} clean runs without drops show zero residue and zero EvDiv "
                   f"(asserted). Clean SARA false incidents per run: none {f(cl['none']['SARA_false_incidents']['mean'], 2)}, "
                   + ", ".join(f"{lv} {f(cl[lv]['SARA_false_incidents']['mean'], 2)}" for lv in ("loose", "mid", "tight") if lv in cl)
                   + ".")
    for lv in ("loose", "mid", "tight"):
        e = c["disturbed"].get(lv)
        if not e:
            continue
        pol = {p: (np.nanmean([e[dd][p]["FRE_state"]["mean"] for dd in DISTURBANCES]),
                   np.nanmean([e[dd][p]["declared_share"] for dd in DISTURBANCES]),
                   np.nanmean([e[dd][p]["share_evdiv_300"] for dd in DISTURBANCES])) for p in POL}
        s = e
        out.append(f"Cap {lv} ({c['caps'][lv]}), mean over the six disturbances: FRE_state B1 {f(pol['B1'][0])} s, "
                   f"B2 {f(pol['B2'][0])} s, SARA {f(pol['SARA'][0])} s; declared before the horizon B1 {pct(pol['B1'][1])}, "
                   f"B2 {pct(pol['B2'][1])}, SARA {pct(pol['SARA'][1])}; runs with EvDiv > 0 at t_end + 300 s "
                   f"B1 {pct(pol['B1'][2])}, B2 {pct(pol['B2'][2])}, SARA {pct(pol['SARA'][2])}; SARA unrepairable gaps "
                   f"per run {f(np.nanmean([s[dd]['SARA']['unrepairable'] for dd in DISTURBANCES]), 1)}, reached HIGH "
                   f"after t_end in {pct(np.nanmean([s[dd]['SARA']['reached_high'] for dd in DISTURBANCES]))} of runs.")
    return out


def runtime(a_log, b_df, c_df):
    """Wall times were measured with 14-16 concurrent processes on a throttled laptop CPU and include one interval
    in which every process stalled at once, so medians per run and first/last completion times are reported
    rather than sums."""
    out = {}
    if a_log.exists():
        last = [ln for ln in a_log.read_text(encoding="utf-8", errors="ignore").splitlines() if "wrote" in ln]
        out["A"] = last[-1].strip().split("(")[-1].rstrip(")") if last else None
    for name, df, key in (("B", b_df, "n_nodes"), ("C", c_df, "cap_level")):
        if df is None:
            continue
        runs = df if name == "B" else df.drop_duplicates(["cap_level", "seed", "history", "dist", "policy"])
        out[f"{name}_runs"] = int(len(runs))
        out[f"{name}_median_wall_per_run_s"] = {str(k): round(float(v), 1) for k, v in runs.groupby(key).wall.median().items()}
        mt = sorted(p.stat().st_mtime for p in (EXT / "raw" / name).rglob("*.pkl"))
        if mt:
            out[f"{name}_jobs_completed_between"] = [time.strftime("%Y-%m-%d %H:%M", time.localtime(mt[0])),
                                                     time.strftime("%Y-%m-%d %H:%M", time.localtime(mt[-1]))]
    return out


def main():
    t0 = time.time()
    numbers = dict(generated=time.strftime("%Y-%m-%d %H:%M"), preregistration=prereg_check())
    a = b = c = None
    b_df = c_df = None
    if (EXT / "ext_a_runs.csv").exists():
        a = analyze_a(pd.read_csv(EXT / "ext_a_runs.csv"))
        numbers["A"] = a
        fig_a(a)
    if (EXT / "ext_b_runs.csv").exists():
        b_df = pd.read_csv(EXT / "ext_b_runs.csv")
        b = analyze_b(b_df, json.loads((EXT / "ext_b_cells.json").read_text()))
        numbers["B"] = b
        fig_b(b)
    if (EXT / "ext_c_runs.csv").exists():
        c_df = pd.read_csv(EXT / "ext_c_runs.csv", low_memory=False)
        c = analyze_c(c_df, json.loads((EXT / "ext_c_cap_calibration.json").read_text()))
        numbers["C"] = c
        fig_c(c)
    numbers["runtime"] = runtime(EXT / "ext_a_log.txt", b_df, c_df)
    vp = EXT / "verification_ext.json"
    if vp.exists():
        numbers["verification"] = json.loads(vp.read_text())
    (EXT / "ext_numbers.json").write_text(json.dumps(clean_json(numbers), indent=1))

    out = []
    w = out.append
    pr = numbers["preregistration"]
    w(f"## Results (generated by `experiments/ext_analyze.py` on {numbers['generated']} from the stored run tables)\n")
    w(f"Pre-registration section unchanged since it was recorded: **{pr['unchanged']}** (sha256 {pr['sha256'][:16]}…). "
      "Every number below is read from `results/extensions/ext_numbers.json`.\n")
    key = {}
    if a:
        key["A"] = findings_a(a)
    if b:
        key["B"] = findings_b(b)
    if c:
        key["C"] = findings_c(c)
    numbers["key_findings"] = key
    (EXT / "ext_numbers.json").write_text(json.dumps(clean_json(numbers), indent=1))
    w("### Key findings (generated statements)\n")
    for ext, lines in key.items():
        for ln in lines:
            w(f"- **{ext}.** {ln}")
    w("")
    if a:
        report_a(a, w)
    if b:
        report_b(b, w)
    if c:
        report_c(c, w)
    if "verification" in numbers:
        v = numbers["verification"]
        cd, ev = v["confirmation_delay"], v["eviction"]
        w("### Hand verification (`results/extensions/verification_ext.json`)\n")
        w(f"Confirmation delay, seed {cd['seed']} / {cd['dist']} / {cd['policy']}: {len(cd['checks'])} quantities "
          f"recomputed by naive code, all match the stored pipeline row: **{cd['all_match']}**. Eviction, seed "
          f"{ev['seed']} / {ev['dist']} / {ev['policy']} at cap '{ev['cap_level']}' ({ev['cap']}), node {ev['node']}: "
          f"{ev['decisions_checked']} admission decisions taken while the mempool was full or the minimum fee was raised "
          f"({ev['evictions_checked']} evictions, {ev['rejections_checked']} rejections) checked against the rule at "
          f"the moment they happened, all match: **{ev['all_decisions_match']}**; evicted-divergence from raw state dumps "
          + "; ".join(f"+{int(r['t_after_end'])} s: hand {r['hand']} vs pipeline {r['pipeline']}"
                      for r in ev["evicted_divergence_checks"]) + f", all match: **{ev['evdiv_all_match']}**.\n")
    rt = numbers["runtime"]
    w("### Runtime\n")
    w("Machine: Intel i5-13500H laptop (16 logical CPUs), 14 worker processes (B and C overlapped, C on 2 processes "
      "while B ran); the CPU ran throttled under full load, and one interval of about 34 minutes stalled every process "
      "at once, so per-run wall times are reported as medians.\n")
    w("; ".join(f"{k}: {v}" for k, v in rt.items()) + ".\n")
    txt = DOC.read_text(encoding="utf-8")
    head, rest = txt.split("<!-- RESULTS:BEGIN -->")
    tail = rest.split("<!-- RESULTS:END -->")[1]
    DOC.write_text(head + "<!-- RESULTS:BEGIN -->\n" + "\n".join(out) + "\n<!-- RESULTS:END -->" + tail,
                   encoding="utf-8")
    print(f"ext_numbers.json, figures and EXTENSIONS.md results written in {time.time() - t0:.0f}s; "
          f"pre-registration unchanged: {pr['unchanged']}")


if __name__ == "__main__":
    main()
