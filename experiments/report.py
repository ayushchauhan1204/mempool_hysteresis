"""Render results/RESULTS.md from numbers.json (and sweeps/verification/calibration JSON).
No number in the output is typed by hand; every value is read from the JSON files."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
DIST = ("partition", "isolation", "loss", "latency", "asymmetric", "burst")
LAB = dict(partition="Partition", isolation="Node isolation", loss="Packet loss", latency="Latency spike",
           asymmetric="Asymmetric link", burst="Transaction burst")


def f(v, nd=1):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:.{nd}f}"


def pval(p):
    if p is None:
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def main():
    n = json.loads((R / "numbers.json").read_text())
    meta = n["meta"]
    cal = meta["calibration"]["values"]
    out = []
    w = out.append
    w("# Results (generated from numbers.json)\n")
    w(f"Held-out seeds {meta['seeds'][0]}–{meta['seeds'][1]} (n = {meta['n_seeds']}), "
      f"{meta['runs']:,} simulation runs, generated {meta['generated']}. Paired tests are two-sided Wilcoxon "
      "signed-rank with Holm correction within each table; r = matched-pairs rank-biserial correlation.\n")
    w(f"Calibration (dev seeds 0–4 only): tau_m = {cal['tau_m']} s, eps_D = {cal['eps_D']} (resolution floor "
      f"applies), beta = {cal['beta']:.2f} blocks, size-proxy limit = {cal['eps_size']}.\n")

    # ---------------- Table I
    t1 = n["table1_rq1"]
    w("## Table I: hysteresis on the no-intervention network (B1), disturbed vs clean history\n")
    w("| Disturbance | Residue AUC, median (tx·s) | State convergence, median (s) | Excess backlog AUC, median (tx·s) "
      "| Δ confirmation latency, median (s) | p (Holm) | Ordering distortion, median | B1 declared before state converged |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in DIST:
        r = t1[d]
        w(f"| {LAB[d]} | {f(r['residue_auc']['median_a'], 0)} | {f(r['T_conv']['median_a'], 0)} "
          f"| {f(r['excess_backlog_auc']['median_a'], 0)} | {f(r['conf_lat_mean']['median_diff'], 2)} "
          f"| {pval(r['conf_lat_mean']['p_holm'])} | {f(r['ordering_distortion']['median_a'], 3)} "
          f"| {r['share_declared_before_state_converged']:.0%} |")
    w("\nClean-history reference: residue is zero at every sample; state convergence 0 s by definition. "
      "Δ confirmation latency compares the identical post-recovery workload (created in the 300 s after the "
      "disturbance ended) between histories.\n")

    # ---------------- Table II
    desc = n["descriptive"]
    t2 = n["table2_policies"]
    w("## Table II: recovery assessment, B1 vs B2 vs SARA\n")
    w("FRE = seconds after the disturbance ended during which the policy reported \"recovered\" while state had "
      "not recovered (FRE_state: residue remained; FRE: residue or backlog debt remained). Means with "
      "medians of time quantities.\n")
    w("| Disturbance | Policy | Detected | Declared, median (s) | State converged, median (s) | FRE_state, mean (s) "
      "| FRE overall, mean (s) | Over-delay, mean (s) | In-band traffic, mean (kB) |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in DIST:
        for p in ("B1", "B2", "SARA"):
            s = desc[d][p]
            w(f"| {LAB[d] if p == 'B1' else ''} | {p} | {s['detected_share']:.0%} | {f(s['T_decl']['median'], 0)} "
              f"| {f(s['T_conv']['median'], 0)} | {f(s['FRE_state']['mean'])} | {f(s['FRE']['mean'])} "
              f"| {f(s['over_delay']['mean'])} | {f(s['inband_kB']['mean'], 0)} |")
    w("")
    w("Paired differences, SARA minus baseline (median difference; Holm-adjusted p; r):\n")
    w("| Disturbance | FRE_state vs B1 | FRE_state vs B2 | FRE vs B1 | FRE vs B2 | State convergence vs B2 | In-band traffic vs B2 |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for d in list(DIST) + ["pooled"]:
        a, b = t2["SARA_vs_B1"][d], t2["SARA_vs_B2"][d]

        def c(r):
            return f"{f(r['median_diff'])} ({pval(r['p_holm'])}; r={r['r_rb']:.2f})"
        w(f"| {LAB.get(d, 'Pooled (per-seed mean)')} | {c(a['FRE_state'])} | {c(b['FRE_state'])} | {c(a['FRE'])} "
          f"| {c(b['FRE'])} | {c(b['T_conv'])} | {c(b['inband_kB'])} |")
    w("")
    pooled = n["pooled_descriptive"]
    w("Monitoring traffic for SARA (incremental mirror), mean per run: "
      f"{f(pooled['SARA']['monitor_kB']['mean'], 0)} kB (full snapshots would be "
      f"{f(pooled['SARA']['monitor_full_kB']['mean'], 0)} kB).\n")

    # ---------------- Table III
    t3 = n["table3_ablation"]
    w("## Table III: ablation, full SARA minus each variant\n")
    w("Negative FRE differences mean the full framework had less false-recovery exposure. Mean of the variant "
      "is shown with the paired median difference and Holm-adjusted p.\n")
    w("| Disturbance | Metric | −D (no divergence detection) | −R (no risk assessment) | −V (no recovery verification) |")
    w("| --- | --- | --- | --- | --- |")
    for d in list(DIST) + ["pooled"]:
        for m in ("FRE_state", "FRE", "T_conv", "inband_kB"):
            cells = []
            for v in ("SARA-D", "SARA-R", "SARA-V"):
                r = t3[f"SARA_vs_{v}"][d][m]
                cells.append(f"variant {f(r['mean_b'])}; Δ {f(r['median_diff'])} ({pval(r['p_holm'])} {r['sig']})")
            w(f"| {LAB.get(d, 'Pooled') if m == 'FRE_state' else ''} | {m} | " + " | ".join(cells) + " |")
    w("")

    # ---------------- false alarms, downstream
    fa = n["false_alarms_clean"]
    w("## False alarms in clean runs\n")
    w("| Policy | Incidents per clean run | Runs with any |")
    w("| --- | --- | --- |")
    for p, v in fa.items():
        w(f"| {p} | {v['mean_incidents_per_run']:.3f} | {v['runs_with_any']:.1%} |")
    w("")
    ds = n["downstream_by_policy"]
    w("## Downstream effect by policy: identical post-recovery workload vs clean history\n")
    w("| Disturbance | Δ confirmation latency B1 (mean s) | B2 | SARA | Ordering distortion B1 (mean) | B2 | SARA |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for d in DIST:
        x = ds[d]
        w(f"| {LAB[d]} | {f(x['B1']['conf_lat_delta'].get('mean'), 2)} | {f(x['B2']['conf_lat_delta'].get('mean'), 2)} "
          f"| {f(x['SARA']['conf_lat_delta'].get('mean'), 2)} | {f(x['B1']['ordering_distortion'].get('mean'), 3)} "
          f"| {f(x['B2']['ordering_distortion'].get('mean'), 3)} | {f(x['SARA']['ordering_distortion'].get('mean'), 3)} |")
    w("")

    # ---------------- sweeps
    sp = R / "sweeps.json"
    if sp.exists():
        sw = json.loads(sp.read_text())
        w("## Robustness sweeps (seeds 2000–2049)\n")
        for name, b in sw.items():
            if name == "calibration_dev_seeds":
                w(f"**{b['title']}** (all six disturbances; SARA only). Added after the held-out run showed "
                  "false incidents in clean runs; the main results keep the pre-specified 5-seed calibration.\n")
                w("| dev seeds | beta (blocks) | false incidents per clean run | FRE_state (s) | FRE (s) | over-delay (s) | declared (s) |")
                w("| --- | --- | --- | --- | --- | --- | --- |")
                for x in b["x"]:
                    bx = b["by_x"][str(x)]["SARA"]
                    cal_x = b["calibration"].get(str(x), {})
                    w(f"| {x} | {f(cal_x.get('beta'), 2)} | {f(bx.get('false_incidents_per_clean_run'), 3)} "
                      f"| {f(bx['FRE_state'].get('mean'))} | {f(bx['FRE'].get('mean'))} "
                      f"| {f(bx['over_delay'].get('mean'))} | {f(bx['T_decl'].get('mean'))} |")
                w("")
                continue
            w(f"**{b['title']}** ({', '.join(b['dists'])}); means per seed.\n")
            w(f"| {b['xlabel']} | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |")
            w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for x in b["x"]:
                bx = b["by_x"][str(x)]
                w(f"| {x} | " + " | ".join(f(bx[p]['T_conv'].get('mean')) for p in ('B1', 'B2', 'SARA')) + " | "
                  + " | ".join(f(bx[p]['FRE_state'].get('mean')) for p in ('B1', 'B2', 'SARA')) + " | "
                  + " | ".join(f(bx[p]['FRE'].get('mean')) for p in ('B1', 'B2', 'SARA')) + " |")
            if b.get("calibration"):
                w("\nRecalibrated on dev seeds: " + "; ".join(
                    f"{k}: beta={v['beta']:.2f}, tau_m={v['tau_m']}, size limit={v['eps_size']:.3f}"
                    for k, v in b["calibration"].items()) + "\n")
            else:
                w("")
    vp = R / "verification.json"
    if vp.exists():
        v = json.loads(vp.read_text())
        w("## Hand verification\n")
        rc = "; ".join(f"+{int(r['t_after_end'])} s: hand {r['hand']} vs pipeline {r['pipeline']}" for r in v["residue_checks"])
        fc = v["fre_check"]
        w(f"Seed {v['seed']}, {v['dist']}, B1. Residue from raw state dumps: {rc}. "
          f"FRE_state by hand {fc['FRE_state_hand']:.0f} s vs pipeline {fc['FRE_state_pipeline']:.0f} s "
          f"(declared {fc['T_decl_hand']:.0f} s, state converged {fc['T_conv_hand']:.0f} s). "
          f"All match: {all(r['match'] for r in v['residue_checks']) and fc['match']}.\n")
    (R / "RESULTS.md").write_text("\n".join(out))
    print("wrote", R / "RESULTS.md")


if __name__ == "__main__":
    main()
