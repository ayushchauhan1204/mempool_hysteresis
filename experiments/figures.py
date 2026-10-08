"""Phase 4 figures, generated only from saved results (results/raw/*, results/numbers.json).

fig1_architecture   system architecture (ground truth feeds only the evaluation layer)
fig2_hysteresis     residue (and excess backlog) over time, clean vs disturbed, per disturbance
fig3_fre            false-recovery exposure per policy: state component and overall
fig4_cost_speed     in-band recovery traffic vs time to state convergence
fig5_robustness     sweeps (written by sweeps.py results, if present)
Each figure is saved as PDF (vector, for the paper) and PNG (300 dpi).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.common import load_dir  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402

FIG = ROOT / "results" / "figures"
RAW = ROOT / "results" / "raw" / "main"
LABEL = dict(partition="Partition", isolation="Node isolation", loss="Packet loss", latency="Latency spike",
             asymmetric="Asymmetric link", burst="Transaction burst")
SHORT = dict(partition="Partition", isolation="Isolation", loss="Loss", latency="Latency",
             asymmetric="Asymmetric", burst="Burst")
PCOL = {"B1": "#c0392b", "B2": "#e08e0b", "SARA": "#1f5fa8", "SARA-D": "#6a9fd4", "SARA-R": "#8e7cc3",
        "SARA-V": "#4aa3a2", "clean": "#555555"}
PNAME = {"B1": "B1 connectivity-only", "B2": "B2 protocol resync", "SARA": "SARA", "SARA-D": "SARA −D",
         "SARA-R": "SARA −R", "SARA-V": "SARA −V"}

plt.rcParams.update({"font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "legend.fontsize": 7,
                     "xtick.labelsize": 7, "ytick.labelsize": 7, "font.family": "DejaVu Sans",
                     "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIG / f"{name}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- Fig. 1
def _box(ax, x, y, w, h, text, fc, ec="#333333", fs=7, bold=False, ls="-"):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=0.9,
                       linestyle=ls)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", wrap=True)
    return b


def _arrow(ax, p, q, color="#333333", ls="-", lw=1.0, style="-|>", rad=0.0):
    a = FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=8, color=color, lw=lw, linestyle=ls,
                        connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)


def fig1():
    fig, ax = plt.subplots(figsize=(7.16, 4.3))
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 12)
    ax.axis("off")
    fs = 6.4
    # panels
    _box(ax, 0.1, 3.0, 6.5, 8.1, "", "#f4f6f8", ec="#9aa5b1")
    _box(ax, 7.0, 3.0, 3.2, 8.1, "", "#f7f4ee", ec="#b5a68a")
    _box(ax, 10.6, 3.0, 9.3, 8.1, "", "#eef4fb", ec="#8fb0d6")
    ax.text(3.35, 11.45, "Simulated blockchain network", ha="center", fontsize=7.5, fontweight="bold")
    ax.text(8.6, 11.45, "Observability", ha="center", fontsize=7.5, fontweight="bold")
    ax.text(15.25, 11.45, "Recovery policies", ha="center", fontsize=7.5, fontweight="bold")

    # network column
    _box(ax, 0.4, 9.45, 2.85, 1.3, "Workload\n(Poisson tx)", "white", fs=fs)
    _box(ax, 3.45, 9.45, 2.85, 1.3, "Mining\n(Poisson blocks)", "white", fs=fs)
    _box(ax, 0.4, 5.25, 5.9, 3.75, "", "white")
    ax.text(3.35, 8.55, "nodes: mempool \u00b7 chain \u00b7 gossip", ha="center", fontsize=fs)
    pts = np.array([[1.1, 7.5], [2.2, 7.85], [3.3, 7.6], [4.6, 7.8], [5.6, 7.0], [5.0, 5.7], [3.7, 6.1],
                    [2.4, 5.6], [1.1, 6.2], [2.9, 6.85]])
    for i, j in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 0), (9, 1), (9, 6), (9, 3),
                 (2, 6), (5, 7), (8, 9), (0, 7)]:
        ax.plot(*zip(pts[i], pts[j]), color="#9aa5b1", lw=0.6, zorder=1)
    ax.scatter(pts[:, 0], pts[:, 1], s=50, color="#1f5fa8", zorder=2, edgecolor="white", lw=0.6)
    ax.plot([4.05, 4.05], [5.4, 8.25], color="#c0392b", lw=1.1, ls=(0, (3, 2)))
    ax.text(4.15, 8.12, "partition", color="#c0392b", fontsize=6, va="center")
    _box(ax, 0.4, 3.2, 5.9, 1.75, "Disturbance injector\npartition \u00b7 isolation \u00b7 loss\nlatency \u00b7 asymmetric \u00b7 burst",
         "#fdecea", fs=6.0)
    _arrow(ax, (1.8, 9.45), (1.8, 9.0))
    _arrow(ax, (4.9, 9.45), (4.9, 9.0))
    _arrow(ax, (3.35, 4.95), (3.35, 5.25))

    # observability
    _box(ax, 7.25, 7.9, 2.7, 1.9, "Connectivity\nmonitor\n(probes, 1 s)", "white", fs=fs)
    _box(ax, 7.25, 5.2, 2.7, 1.9, "State mirror\n(mempool\nevents, tips)", "white", fs=fs)
    _arrow(ax, (6.3, 8.2), (7.25, 8.6))
    _arrow(ax, (6.3, 6.4), (7.25, 6.15))

    # policies
    _box(ax, 10.9, 9.65, 3.9, 1.1, "B1: connectivity-only", "#fbe3e0", fs=fs)
    _box(ax, 15.15, 9.65, 4.45, 1.1, "B2: protocol resync", "#fdf0d8", fs=fs)
    ax.text(15.25, 8.95, "SARA: State-Aware Recovery Audit", ha="center", fontsize=7, fontweight="bold",
            color="#1f5fa8")
    xs = [10.9, 13.15, 15.4, 17.65]
    names = ["\u2460 State\nmonitoring", "\u2461 Divergence\ndetection", "\u2462 Risk\nassessment",
             "\u2463 Recovery\nverification"]
    subs = ["mirror", "Jaccard D,\ngaps g\u1d62", "LOW \u2192\nCRITICAL", "LOW for W\naudits"]
    for x, n_, sb in zip(xs, names, subs):
        _box(ax, x, 6.55, 1.95, 1.95, "", "white", ec="#1f5fa8")
        ax.text(x + 0.975, 7.85, n_, ha="center", va="center", fontsize=6.2)
        ax.text(x + 0.975, 7.0, sb, ha="center", va="center", fontsize=5.4, color="#1f5fa8")
    for a, b in zip(xs[:-1], xs[1:]):
        _arrow(ax, (a + 1.95, 7.5), (b, 7.5), color="#1f5fa8")
    _box(ax, 13.15, 3.5, 4.25, 1.6, "Targeted pull reconciliation\n(missing IDs, usable links)", "#e3eefa",
         ec="#1f5fa8", fs=6.0)
    _arrow(ax, (16.35, 6.55), (15.6, 5.1), color="#1f5fa8")
    ax.text(16.3, 5.75, "tier sets\nintensity", fontsize=5.4, color="#1f5fa8")
    _arrow(ax, (13.15, 4.0), (6.3, 5.3), color="#1f5fa8")
    ax.text(8.6, 3.95, "repairs over\np2p links", fontsize=5.8, color="#1f5fa8", ha="center")
    # monitor and mirror feeds
    _arrow(ax, (9.95, 9.3), (10.9, 10.05), color="#7a6a4f")
    _arrow(ax, (9.95, 9.3), (15.5, 9.65), color="#7a6a4f")
    _arrow(ax, (9.95, 8.4), (10.9, 7.9), color="#7a6a4f")
    _arrow(ax, (9.95, 6.15), (10.9, 7.1), color="#7a6a4f")

    # ground truth / evaluation band
    _box(ax, 0.4, 0.2, 7.4, 2.0, "Ground-truth evaluator (omniscient)\nresidue Res(t)\nexcess backlog vs paired clean run",
         "#eeeeee", ec="#555555", ls=(0, (4, 2)), fs=6.0)
    _box(ax, 10.9, 0.2, 8.7, 2.0, "Evaluation layer\ndeclared vs true recovery \u00b7 FRE \u00b7 cost \u00b7 Wilcoxon",
         "#eeeeee", ec="#555555", fs=6.0)
    _arrow(ax, (3.35, 3.0), (3.35, 2.2), color="#555555", ls=(0, (3, 2)))
    _arrow(ax, (7.8, 1.2), (10.9, 1.2), color="#555555", ls=(0, (3, 2)))
    ax.text(9.35, 1.55, "never visible\nto policies", fontsize=5.6, color="#555555", ha="center")
    _arrow(ax, (15.25, 3.0), (15.25, 2.2), color="#555555")
    ax.text(15.45, 2.45, "recovery declarations", fontsize=5.6, color="#555555")
    save(fig, "fig1_architecture")


# ---------------------------------------------------------------- Fig. 2
def _mean_ci(arr):
    arr = np.asarray(arr, float)
    m = np.nanmean(arr, axis=0)
    se = np.nanstd(arr, axis=0, ddof=1) / np.sqrt(np.sum(np.isfinite(arr), axis=0).clip(min=1))
    return m, m - 1.96 * se, m + 1.96 * se


def fig2(curves, df, cfg):
    fig, axes = plt.subplots(2, 3, figsize=(7.16, 3.9), sharex=True)
    seeds = sorted({k[0] for k in curves})
    t_rel = None
    for ax, d in zip(axes.flat, DISTURBANCES):
        te = cfg["dist_start"] + (cfg["burst_duration"] if d == "burst" else cfg["dist_duration"])
        dur = te - cfg["dist_start"]
        key = f"res@{te:g}"
        series = {}
        for lab, (hist, dd, pol) in {"clean": ("clean", None, "B1"), "B1": ("disturbed", d, "B1"),
                                     "B2": ("disturbed", d, "B2"), "SARA": ("disturbed", d, "SARA")}.items():
            rows, ex = [], []
            for s in seeds:
                c = curves.get((s, hist, dd, pol))
                ref = curves.get((s, "clean", None, "B1"))
                if c is None or ref is None:
                    continue
                t = c["t"]
                rows.append(np.nan_to_num(c[key], nan=0.0))
                ex.append(np.clip(c["pend"] - ref["pend"], 0, None))
            if not rows:
                continue
            series[lab] = (np.vstack(rows), np.vstack(ex))
            t_rel = t - te
        win = (t_rel >= -dur - 20) & (t_rel <= 420)
        ax.axvspan(-dur, 0, color="#f5c6c0", alpha=0.45, lw=0)
        for lab in ("clean", "B1", "B2", "SARA"):
            if lab not in series:
                continue
            m, lo, hi = _mean_ci(series[lab][0])
            ax.plot(t_rel[win], m[win], color=PCOL[lab], lw=1.1,
                    label={"clean": "clean history", "B1": "disturbed, B1", "B2": "disturbed, B2",
                           "SARA": "disturbed, SARA"}[lab])
            ax.fill_between(t_rel[win], lo[win], hi[win], color=PCOL[lab], alpha=0.15, lw=0)
        # excess backlog of the no-intervention network on a twin axis
        ax2 = ax.twinx()
        m, lo, hi = _mean_ci(series["B1"][1])
        ax2.plot(t_rel[win], m[win], color="#7f7f7f", lw=0.9, ls=(0, (3, 2)))
        ax2.set_ylim(bottom=0)
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(True)
        ax2.spines["right"].set_color("#b0b0b0")
        ax2.tick_params(axis="y", labelsize=6, colors="#7f7f7f")
        if d in ("loss", "burst"):
            ax2.set_ylabel("excess backlog (tx)", color="#7f7f7f", fontsize=6.5)
        sub = df[(df.history == "disturbed") & (df.dist == d) & (df.policy == "B1")]
        decl = float(np.median(sub.T_decl))
        ax.axvline(decl, color=PCOL["B1"], lw=0.8, ls=":")
        ax.set_title(LABEL[d])
        ax.set_ylim(bottom=0)
        top = max(np.nanmax(_mean_ci(series[k][0])[2][win]) for k in series)
        if not np.isfinite(top) or top < 1:
            ax.set_ylim(0, 10)
            ax.text(0.97, 0.9, "no residue", transform=ax.transAxes, ha="right", va="top", fontsize=6.5,
                    color="#555555")
        if d in ("partition", "latency"):
            ax.set_ylabel("residue (tx)")
        if ax in axes[1]:
            ax.set_xlabel("time since disturbance ended (s)")
    h, l = axes[0, 0].get_legend_handles_labels()
    h.append(plt.Line2D([], [], color="#7f7f7f", ls=(0, (3, 2)), lw=0.9))
    l.append("excess backlog, B1 (right axis)")
    h.append(plt.Line2D([], [], color=PCOL["B1"], ls=":", lw=0.8))
    l.append("B1 declares recovery (median)")
    fig.legend(h, l, loc="lower center", ncol=6, frameon=False, bbox_to_anchor=(0.5, -0.04), fontsize=6.5)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, "fig2_hysteresis")


# ---------------------------------------------------------------- Fig. 3
def fig3(df):
    pols = ["B1", "B2", "SARA"]
    dd = df[df.history == "disturbed"]
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 2.35))
    x = np.arange(len(DISTURBANCES))
    w = 0.26
    for ax, metric, title in zip(axes, ["FRE_state", "FRE"],
                                 ["(a) state component: certified while residue remained",
                                  "(b) overall: residue or backlog debt remained"]):
        for k, p in enumerate(pols):
            means, los, his = [], [], []
            for d in DISTURBANCES:
                v = dd[(dd.dist == d) & (dd.policy == p)][metric].values.astype(float)
                rng = np.random.default_rng(1)
                bs = rng.choice(v, (2000, len(v))).mean(axis=1) if len(v) else np.array([np.nan])
                means.append(v.mean() if len(v) else np.nan)
                los.append(np.quantile(bs, .025))
                his.append(np.quantile(bs, .975))
            means, los, his = map(np.asarray, (means, los, his))
            ax.bar(x + (k - 1) * w, means, w, color=PCOL[p], label=PNAME[p],
                   yerr=[means - los, his - means], error_kw=dict(lw=0.6, capsize=1.5))
            for xi, mv in zip(x + (k - 1) * w, means):
                if mv == 0:
                    ax.text(xi, 0.08, "0", ha="center", va="bottom", fontsize=6, color=PCOL[p], fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([SHORT[d] for d in DISTURBANCES], rotation=25, ha="right", rotation_mode="anchor")
        ax.set_yscale("symlog", linthresh=1)
        ax.set_ylabel("false-recovery exposure (s)")
        ax.set_title(title)
    axes[0].legend(frameon=False, loc="upper right")
    fig.tight_layout()
    save(fig, "fig3_fre")


# ---------------------------------------------------------------- Fig. 4
def fig4(df):
    dd = df[df.history == "disturbed"]
    pols = ["B1", "B2", "SARA", "SARA-D", "SARA-R", "SARA-V"]
    marks = {"B1": "X", "B2": "s", "SARA": "o", "SARA-D": "^", "SARA-R": "v", "SARA-V": "D"}
    shown = ["partition", "isolation", "asymmetric", "latency"]
    fig, axes = plt.subplots(1, 4, figsize=(7.16, 2.0))
    for ax, d in zip(axes, shown):
        for p in pols:
            sub = dd[(dd.dist == d) & (dd.policy == p)]
            ax.scatter(sub.inband_kB.mean(), sub.T_conv.mean(), marker=marks[p], color=PCOL[p], s=28,
                       edgecolor="white", lw=0.4, label=PNAME[p], zorder=3)
        ax.set_title(LABEL[d])
        ax.set_xlabel("in-band traffic (kB)")
        ys = [dd[(dd.dist == d) & (dd.policy == p)].T_conv.mean() for p in pols]
        ys = [y for y in ys if np.isfinite(y) and y > 0]
        if ys and max(ys) / min(ys) > 8:
            ax.set_yscale("log")
            ax.yaxis.set_major_locator(matplotlib.ticker.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
            ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        else:
            ax.set_ylim(bottom=0)
        if d == "partition":
            ax.set_ylabel("time to state convergence (s)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=6, frameon=False, bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    save(fig, "fig4_cost_speed")


# ---------------------------------------------------------------- Fig. 5
def fig5():
    p = ROOT / "results" / "sweeps.json"
    if not p.exists():
        print("fig5: sweeps.json not found, skipped")
        return
    sw = json.loads(p.read_text())
    panels = [k for k in ("partition_duration", "loss_lossy") if k in sw]
    fig, axes = plt.subplots(1, len(panels) * 2, figsize=(7.16, 2.0))
    axes = np.atleast_1d(axes)
    k = 0
    for name in panels:
        block = sw[name]
        xs = block["x"]
        for metric, ylab in (("T_conv", "time to state convergence (s)"),
                             ("FRE_state", "FRE, state component (s)")):
            ax = axes[k]
            k += 1
            for pol in ("B1", "B2", "SARA"):
                m = [block["by_x"][str(x)][pol][metric]["mean"] for x in xs]
                lo = [block["by_x"][str(x)][pol][metric]["ci95"][0] for x in xs]
                hi = [block["by_x"][str(x)][pol][metric]["ci95"][1] for x in xs]
                ax.plot(xs, m, marker="o", ms=3, color=PCOL[pol], lw=1, label=PNAME[pol])
                ax.fill_between(xs, lo, hi, color=PCOL[pol], alpha=0.15, lw=0)
            ax.set_xlabel(block["xlabel"])
            ax.set_ylabel(ylab)
            ax.set_yscale("symlog", linthresh=1)
            ax.set_title(block["title"])
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.1))
    fig.tight_layout(rect=(0, 0.06, 1, 1), w_pad=1.6)
    save(fig, "fig5_robustness")


def main(raw=RAW):
    df, curves, post = load_dir(raw)
    import pandas as pd  # noqa: F401
    df["inband_kB"] = (df.announced * 36 + df.requested * 36 + df.transfers * 250) / 1000.0
    cfg = json.loads((Path(raw) / "config.json").read_text())
    fig1()
    fig2(curves, df, cfg)
    fig3(df)
    fig4(df)
    fig5()
    print("figures written to", FIG)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else RAW)
