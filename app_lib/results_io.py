"""Read-only loaders and table builders for the stored results.

Main study: results/numbers.json, results/sweeps.json, results/verification.json, results/RESULTS.md and
results/figures/. Extensions: results/extensions/ext_numbers.json, EXTENSIONS.md, verification_ext.json,
ext_c_cap_calibration.json and results/extensions/figures/. Every number shown comes from these files; the table
builders only select and rename values (no statistic is recomputed), and each returns the key path it read so the
page can show where a number comes from.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
EXT = RESULTS / "extensions"
FILES = dict(
    numbers=RESULTS / "numbers.json", sweeps=RESULTS / "sweeps.json", verification=RESULTS / "verification.json",
    results_md=RESULTS / "RESULTS.md", calibration=RESULTS / "dev" / "calibration.json",
    ext_numbers=EXT / "ext_numbers.json", extensions_md=EXT / "EXTENSIONS.md",
    ext_verification=EXT / "verification_ext.json", ext_caps=EXT / "ext_c_cap_calibration.json",
    ext_cells=EXT / "ext_b_cells.json", readme=ROOT / "README.md",
)
GENERATOR = dict(
    numbers="python experiments/analyze.py", sweeps="python experiments/sweeps.py",
    verification="python experiments/verify_by_hand.py", results_md="python experiments/report.py",
    calibration="python experiments/calibrate.py", ext_numbers="python experiments/ext_analyze.py",
    extensions_md="python experiments/ext_analyze.py", ext_verification="python experiments/ext_verify_by_hand.py",
    ext_caps="python experiments/ext_c_capacity.py --calibrate", ext_cells="python experiments/ext_b_scale.py",
    readme="(part of the project)",
)
DISTS = ("partition", "isolation", "loss", "latency", "asymmetric", "burst")
LAB = dict(partition="Partition", isolation="Node isolation", loss="Packet loss", latency="Latency spike",
           asymmetric="Asymmetric link", burst="Transaction burst", pooled="Pooled (per-seed mean)")
MAIN_FIGURES = [
    ("fig1_architecture", "System architecture: ground truth feeds only the evaluation layer."),
    ("fig2_hysteresis", "Residue (and excess backlog) over time, clean vs disturbed, per disturbance."),
    ("fig3_fre", "False-recovery exposure per policy: state component and overall."),
    ("fig4_cost_speed", "In-band recovery traffic vs time to state convergence."),
    ("fig5_robustness", "Robustness sweeps."),
]
EXT_FIGURES = [
    ("A", "ext_a_excess_delay", "Extension A: per-run mean excess delay of the exposed workload."),
    ("B", "ext_b_fre_state", "Extension B: FRE_state after a partition per cell."),
    ("B", "ext_b_sara_costs", "Extension B: SARA's false incidents and over-delay per cell."),
    ("C", "ext_c_capacity", "Extension C: bounded mempools."),
]


class ResultsMissing(FileNotFoundError):
    """A stored results file is missing or unreadable; the message says how to regenerate it."""


def _path(key: str) -> Path:
    return FILES[key]


def load_json(key: str, path: Path | None = None) -> dict:
    p = Path(path) if path else _path(key)
    if not p.exists():
        raise ResultsMissing(f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p} not found. "
                             f"Generate it with `{GENERATOR.get(key, '')}` (see README).")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ResultsMissing(f"{p.name} is not valid JSON ({e}). Regenerate it with `{GENERATOR.get(key, '')}`.")


def load_text(key: str, path: Path | None = None) -> str:
    p = Path(path) if path else _path(key)
    if not p.exists():
        raise ResultsMissing(f"{p.name} not found. Generate it with `{GENERATOR.get(key, '')}`.")
    return p.read_text(encoding="utf-8")


def figure(name: str, ext: bool = False) -> Path | None:
    p = (EXT / "figures" if ext else RESULTS / "figures") / f"{name}.png"
    return p if p.exists() else None


def cap_presets() -> dict:
    """Extension C cap levels computed on dev seeds (loose / mid / tight), or {} if not generated."""
    try:
        return {k: int(v) for k, v in load_json("ext_caps")["caps"].items()}
    except ResultsMissing:
        return {}


def _src(file: str, *path) -> str:
    return f"{file} → " + "".join(f"[{p}]" for p in path)


# ------------------------------------------------------------------------------------------ main study
def meta_summary(n: dict) -> dict:
    m = n["meta"]
    return dict(seeds=f"{m['seeds'][0]}–{m['seeds'][1]}", n_seeds=m["n_seeds"], runs=m["runs"],
                generated=m["generated"], calibration=m["calibration"]["values"])


def headline_table(n: dict) -> tuple[pd.DataFrame, str]:
    rows = []
    for d in DISTS:
        for p in ("B1", "B2", "SARA"):
            s = n["descriptive"][d][p]
            rows.append({"Disturbance": LAB[d], "Policy": p, "Detected (share)": s["detected_share"],
                         "Declared, median (s)": s["T_decl"]["median"],
                         "State converged, median (s)": s["T_conv"]["median"],
                         "FRE_state, mean (s)": s["FRE_state"]["mean"],
                         "Runs with FRE_state > 0 (share)": s["premature_share"],
                         "FRE, mean (s)": s["FRE"]["mean"], "In-band traffic, mean (kB)": s["inband_kB"]["mean"]})
    for p in ("B1", "B2", "SARA"):
        s = n["pooled_descriptive"][p]
        rows.append({"Disturbance": LAB["pooled"], "Policy": p, "Detected (share)": None,
                     "Declared, median (s)": s["T_decl"]["median"], "State converged, median (s)": s["T_conv"]["median"],
                     "FRE_state, mean (s)": s["FRE_state"]["mean"], "Runs with FRE_state > 0 (share)": None,
                     "FRE, mean (s)": s["FRE"]["mean"], "In-band traffic, mean (kB)": s["inband_kB"]["mean"]})
    return pd.DataFrame(rows), ("numbers.json → [descriptive][<disturbance>][<policy>]: detected_share, "
                                "T_decl.median, T_conv.median, FRE_state.mean, premature_share, FRE.mean, "
                                "inband_kB.mean; pooled rows → [pooled_descriptive][<policy>]")


def hysteresis_table(n: dict) -> tuple[pd.DataFrame, str]:
    rows = []
    for d in DISTS:
        r = n["table1_rq1"][d]
        rows.append({"Disturbance": LAB[d], "Residue AUC, median (tx·s)": r["residue_auc"]["median_a"],
                     "State convergence, median (s)": r["T_conv"]["median_a"],
                     "Excess backlog AUC, median (tx·s)": r["excess_backlog_auc"]["median_a"],
                     "Δ confirmation latency, median (s)": r["conf_lat_mean"]["median_diff"],
                     "p (Holm)": r["conf_lat_mean"]["p_holm"],
                     "Ordering distortion, median": r["ordering_distortion"]["median_a"],
                     "B1 declared before state converged (share)": r["share_declared_before_state_converged"]})
    return pd.DataFrame(rows), ("numbers.json → [table1_rq1][<disturbance>]: residue_auc.median_a, T_conv.median_a, "
                                "excess_backlog_auc.median_a, conf_lat_mean.median_diff / p_holm, "
                                "ordering_distortion.median_a, share_declared_before_state_converged")


def paired_table(n: dict, metric: str) -> tuple[pd.DataFrame, str]:
    rows = []
    for d in list(DISTS) + ["pooled"]:
        row = {"Disturbance": LAB[d]}
        for base in ("B1", "B2"):
            r = n["table2_policies"][f"SARA_vs_{base}"][d][metric]
            row[f"vs {base}: median diff"] = r["median_diff"]
            row[f"vs {base}: 95% CI"] = f"[{r['ci95_median_diff'][0]:.1f}, {r['ci95_median_diff'][1]:.1f}]"
            row[f"vs {base}: p (Holm)"] = r["p_holm"]
            row[f"vs {base}: r"] = r["r_rb"]
        rows.append(row)
    return pd.DataFrame(rows), f"numbers.json → [table2_policies][SARA_vs_B1 | SARA_vs_B2][<disturbance>][{metric}]"


def breakdown_table(n: dict, dist: str, stat: str = "mean") -> tuple[pd.DataFrame, str]:
    metrics = ("T_det", "T_decl", "T_conv", "T_bk", "FRE_state", "FRE", "over_delay", "resid_at_decl", "inband_kB",
               "reopened")
    rows = []
    for p, s in n["descriptive"][dist].items():
        row = {"Policy": p}
        for m in metrics:
            row[m] = s[m].get(stat)
        row.update({"detected (share)": s["detected_share"], "FRE_state > 0 (share)": s["premature_share"],
                    "T_conv censored (share)": s["conv_censored_share"]})
        rows.append(row)
    return pd.DataFrame(rows), f"numbers.json → [descriptive][{dist}][<policy>][<metric>][{stat}]"


def ablation_table(n: dict, metric: str) -> tuple[pd.DataFrame, str]:
    rows = []
    for d in list(DISTS) + ["pooled"]:
        row = {"Disturbance": LAB[d]}
        for v in ("SARA-D", "SARA-R", "SARA-V"):
            r = n["table3_ablation"][f"SARA_vs_{v}"][d][metric]
            row[f"{v} mean"] = r["mean_b"]
            row[f"SARA − {v}, median"] = r["median_diff"]
            row[f"{v} p (Holm)"] = r["p_holm"]
        rows.append(row)
    return pd.DataFrame(rows), f"numbers.json → [table3_ablation][SARA_vs_<variant>][<disturbance>][{metric}]"


def false_alarms_table(n: dict) -> tuple[pd.DataFrame, str]:
    rows = [{"Policy": p, "Incidents per clean run": v["mean_incidents_per_run"], "Runs with any (share)": v["runs_with_any"]}
            for p, v in n["false_alarms_clean"].items()]
    return pd.DataFrame(rows), "numbers.json → [false_alarms_clean][<policy>]"


def downstream_table(n: dict) -> tuple[pd.DataFrame, str]:
    rows = []
    for d in DISTS:
        x = n["downstream_by_policy"][d]
        row = {"Disturbance": LAB[d]}
        for p in ("B1", "B2", "SARA"):
            row[f"Δ conf. latency {p}, mean (s)"] = x[p]["conf_lat_delta"].get("mean")
        for p in ("B1", "B2", "SARA"):
            row[f"Ordering distortion {p}, mean"] = x[p]["ordering_distortion"].get("mean")
        rows.append(row)
    return pd.DataFrame(rows), "numbers.json → [downstream_by_policy][<disturbance>][<policy>]"


def sweep_names(sw: dict) -> list:
    return [k for k in sw if k != "calibration_dev_seeds"]


def sweep_table(sw: dict, name: str) -> tuple[pd.DataFrame, str]:
    b = sw[name]
    rows = []
    for x in b["x"]:
        bx = b["by_x"][str(x)]
        row = {b["xlabel"]: str(x)}
        for metric in ("T_conv", "FRE_state", "FRE"):
            for p in ("B1", "B2", "SARA"):
                row[f"{p} {metric}, mean"] = bx[p][metric].get("mean")
        rows.append(row)
    return pd.DataFrame(rows), f"sweeps.json → [{name}][by_x][<x>][<policy>][T_conv | FRE_state | FRE][mean]"


def sweep_long(sw: dict, name: str) -> pd.DataFrame:
    """Long form (x, policy, metric, mean, ci_lo, ci_hi) for plotting; values as stored."""
    b = sw[name]
    rows = []
    for x in b["x"]:
        for p in ("B1", "B2", "SARA"):
            for metric in ("T_conv", "FRE_state", "FRE"):
                v = b["by_x"][str(x)][p][metric]
                rows.append(dict(x=str(x), policy=p, metric=metric, mean=v.get("mean"),
                                 ci_lo=(v.get("ci95") or [None, None])[0], ci_hi=(v.get("ci95") or [None, None])[1]))
    return pd.DataFrame(rows)


def calibration_check_table(sw: dict) -> tuple[pd.DataFrame, str]:
    b = sw["calibration_dev_seeds"]
    rows = []
    for x in b["x"]:
        s = b["by_x"][str(x)]["SARA"]
        cal = b["calibration"].get(str(x), {})
        rows.append({"Dev seeds used": x, "beta (blocks)": cal.get("beta"), "tau_m (s)": cal.get("tau_m"),
                     "False incidents per clean run": s.get("false_incidents_per_clean_run"),
                     "FRE_state, mean (s)": s["FRE_state"].get("mean"), "FRE, mean (s)": s["FRE"].get("mean"),
                     "Over-delay, mean (s)": s["over_delay"].get("mean"), "Declared, mean (s)": s["T_decl"].get("mean")})
    return pd.DataFrame(rows), "sweeps.json → [calibration_dev_seeds][by_x][<dev seeds>][SARA], [calibration]"


def verification_table(v: dict) -> tuple[pd.DataFrame, str]:
    rows = [{"Check": f"residue at t_end + {r['t_after_end']:.0f} s", "By hand": r["hand"], "Pipeline": r["pipeline"],
             "Match": r["match"]} for r in v["residue_checks"]]
    fc = v["fre_check"]
    for k in ("T_decl", "T_conv", "FRE_state"):
        rows.append({"Check": f"B1 {k} (s)", "By hand": fc[f"{k}_hand"], "Pipeline": fc[f"{k}_pipeline"],
                     "Match": fc["match"]})
    return pd.DataFrame(rows), "verification.json → [residue_checks], [fre_check]"


# ------------------------------------------------------------------------------------------ extensions
def md_sections(text: str) -> dict:
    """Split EXTENSIONS.md into its parts: preregistration, changelog, results, discussion."""
    out = {}
    if "<!-- PREREG:BEGIN -->" in text:
        out["preregistration"] = text.split("<!-- PREREG:BEGIN -->")[1].split("<!-- PREREG:END -->")[0].strip()
        rest = text.split("<!-- PREREG:END -->")[1]
    else:
        rest = text
    if "<!-- RESULTS:BEGIN -->" in rest:
        out["changelog"] = rest.split("<!-- RESULTS:BEGIN -->")[0].strip()
        res, tail = rest.split("<!-- RESULTS:BEGIN -->")[1].split("<!-- RESULTS:END -->")
        out["results"] = res.strip()
        out["discussion"] = tail.strip()
    out["intro"] = text.split("<!-- PREREG:BEGIN -->")[0].strip() if "<!-- PREREG:BEGIN -->" in text else ""
    return out


def md_subsection(md: str, heading: str) -> str:
    """The body of the markdown section whose heading starts with `heading` (up to the next heading of the same
    or a higher level)."""
    lines = md.splitlines()
    out, level = [], None
    for ln in lines:
        m = re.match(r"^(#+)\s+(.*)", ln)
        if m:
            if level is not None and len(m.group(1)) <= level:
                break
            if level is None and m.group(2).startswith(heading):
                level = len(m.group(1))
                continue
        if level is not None:
            out.append(ln)
    return "\n".join(out).strip()


def without_images(md: str) -> str:
    """Drop markdown image lines (the page shows the PNGs itself)."""
    return "\n".join(ln for ln in md.splitlines() if not ln.strip().startswith("!["))


def ext_a_table(e: dict, sample: str = "heldout") -> tuple[pd.DataFrame, str]:
    s = e["A"]["samples"][sample]
    rows = []
    for d in list(DISTS) + ["pooled"]:
        row = {"Disturbance": LAB[d]}
        for p in ("B1", "B2", "SARA"):
            row[f"{p} vs clean, median (s)"] = None if d == "pooled" else s["A1_harm_vs_clean"][d][p]["median_diff"]
        for b in ("B1", "B2"):
            r = s["A2_policies"]["exposed_x_mean"][f"SARA_vs_{b}"][d]
            row[f"SARA − {b}, median (s)"] = r["median_diff"]
            row[f"SARA − {b}, p (Holm)"] = r["p_holm"]
        kq = s["key_question"][d]
        row["Worse off under B1?"] = "yes" if kq["B1"] else "no"
        row["Worse off under B2?"] = "yes" if kq["B2"] else "no"
        rows.append(row)
    return pd.DataFrame(rows), (f"ext_numbers.json → [A][samples][{sample}][A1_harm_vs_clean][<disturbance>][<policy>]"
                                f"[median_diff]; [A2_policies][exposed_x_mean][SARA_vs_<B>][<disturbance>]; "
                                f"[key_question]")


def ext_a_windows_table(e: dict, sample: str = "heldout") -> tuple[pd.DataFrame, str]:
    s = e["A"]["samples"][sample]["descriptive"]
    rows = []
    for d in DISTS:
        for p in ("B1", "B2", "SARA"):
            x = s[d][p]
            rows.append({"Disturbance": LAB[d], "Policy": p, "before (s)": x["before_x_mean"].get("median"),
                         "during (s)": x["during_x_mean"].get("median"), "after (s)": x["after_x_mean"].get("median"),
                         "never-confirmed extra": x["exposed_x_never_extra"].get("median"),
                         "BCD": x["blk_bcd"].get("median"), "FRE_state (s)": x["m_FRE_state"].get("median")})
    return pd.DataFrame(rows), (f"ext_numbers.json → [A][samples][{sample}][descriptive][<disturbance>][<policy>]"
                                f"[<window>_x_mean | exposed_x_never_extra | blk_bcd | m_FRE_state][median]")


def ext_b_table(e: dict) -> tuple[pd.DataFrame, str]:
    b = e["B"]
    rows = []
    for c in b["order"]:
        r = b["cells"].get(c)
        if not r:
            continue
        ci = r["cell"]
        rows.append({"Topology": ci["topology"].replace("_", " "), "Nodes": ci["n_nodes"], "Degree": ci["degree"],
                     "Load": ci["load"], "Diameter": r["graph"]["diameter_mean"],
                     "B1 residue AUC, median": r["B1_residue_auc_median"],
                     "Certified with residue: B1": r["B1"]["certified_with_residue"],
                     "Certified with residue: B2": r["B2"]["certified_with_residue"],
                     "Certified with residue: SARA": r["SARA"]["certified_with_residue"],
                     "FRE_state mean: B1 (s)": r["B1"]["FRE_state"]["mean"],
                     "FRE_state mean: B2 (s)": r["B2"]["FRE_state"]["mean"],
                     "FRE_state mean: SARA (s)": r["SARA"]["FRE_state"]["mean"],
                     "SARA − B2, median (s)": r["SARA_vs_B2_FRE_state"]["median_diff"],
                     "SARA − B2, p (Holm)": r["SARA_vs_B2_FRE_state"]["p_holm"],
                     "Advantage vs B2": r["advantage_vs_B2"], "SARA over-delay (s)": r["SARA"]["over_delay"]["mean"],
                     "SARA false incidents / clean run": r["SARA_false_incidents"]["mean"]})
    return pd.DataFrame(rows), "ext_numbers.json → [B][cells][<cell>] (partition runs; see the scope change in the change log)"


def ext_a_spearman_table(e: dict, sample: str = "heldout") -> tuple[pd.DataFrame, str]:
    s = e["A"]["samples"][sample]["A3_spearman"]
    rows = [{"Disturbance": LAB[d], "B1 ρ": s["B1"][d]["rho"], "B1 p": s["B1"][d]["p"], "B2 ρ": s["B2"][d]["rho"],
             "B2 p": s["B2"][d]["p"]} for d in DISTS]
    return pd.DataFrame(rows), f"ext_numbers.json → [A][samples][{sample}][A3_spearman][<policy>][<disturbance>]"


def ext_b_other_table(e: dict) -> tuple[pd.DataFrame, str]:
    rows = []
    for c in e["B"]["order"]:
        r = e["B"]["cells"].get(c)
        if not r or "isolation_asymmetric" not in r:
            continue
        o, ci = r["isolation_asymmetric"], r["cell"]
        row = {"Topology": ci["topology"].replace("_", " "), "Nodes": ci["n_nodes"], "Degree": ci["degree"],
               "Load": ci["load"]}
        for dd in ("isolation", "asymmetric"):
            for p in ("B1", "B2", "SARA"):
                row[f"Certified with residue, {dd}: {p}"] = o[p]["certified_with_residue_by_dist"][dd]
        for p in ("B1", "B2", "SARA"):
            row[f"FRE_state mean: {p} (s)"] = o[p]["FRE_state"]["mean"]
        row["SARA − B2, median (s)"] = o["SARA_vs_B2_FRE_state"]["median_diff"]
        row["SARA − B2, p (Holm)"] = o["SARA_vs_B2_FRE_state"]["p_holm"]
        row["Advantage vs B2"] = o["advantage_vs_B2"]
        rows.append(row)
    return pd.DataFrame(rows), "ext_numbers.json → [B][cells][<cell>][isolation_asymmetric] (10- and 20-node cells)"


def ext_c_paired_table(e: dict, level: str) -> tuple[pd.DataFrame, str]:
    rows = []
    for d in DISTS:
        x = e["C"]["paired"][level][d]
        rows.append({"Disturbance": LAB[d], "SARA − B1, median (s)": x["SARA_vs_B1"]["median_diff"],
                     "vs B1 p (Holm)": x["SARA_vs_B1"]["p_holm"], "SARA − B2, median (s)": x["SARA_vs_B2"]["median_diff"],
                     "vs B2 p (Holm)": x["SARA_vs_B2"]["p_holm"]})
    return pd.DataFrame(rows), f"ext_numbers.json → [C][paired][{level}][<disturbance>][SARA_vs_<B>] (FRE_state)"


def ext_verification_table(v: dict) -> tuple[pd.DataFrame, str]:
    cd, ev = v["confirmation_delay"], v["eviction"]
    rows = [{"Check": f"confirmation delay: {c['quantity']}", "By hand": c["hand"], "Pipeline": c["pipeline"],
             "Match": c["match"]} for c in cd["checks"]]
    rows += [{"Check": f"evicted-divergence at t_end + {r['t_after_end']:.0f} s", "By hand": r["hand"],
              "Pipeline": r["pipeline"], "Match": r["match"]} for r in ev["evicted_divergence_checks"]]
    rows.append({"Check": f"admission decisions at node {ev['node']} ({ev['evictions_checked']} evictions, "
                          f"{ev['rejections_checked']} rejections)", "By hand": ev["decisions_checked"],
                 "Pipeline": ev["decisions_checked"], "Match": ev["all_decisions_match"]})
    return pd.DataFrame(rows), "results/extensions/verification_ext.json"


def ext_b_recal_table(e: dict) -> tuple[pd.DataFrame, str]:
    rows = []
    for c in e["B"]["order"]:
        r = e["B"]["cells"].get(c)
        if not r or "SARA_recalibrated" not in r:
            continue
        x = r["SARA_recalibrated"]
        v = x.get("values") or {}
        rows.append({"Cell": c, "tau_m (s)": v.get("tau_m"), "eps_D": v.get("eps_D"), "beta (blocks)": v.get("beta"),
                     "Certified with residue": x["certified_with_residue"], "FRE_state mean (s)": x["FRE_state"]["mean"],
                     "Over-delay (s)": x["over_delay"]["mean"],
                     "False incidents / clean run": x["false_incidents"]["mean"],
                     "Calibrated SARA: false incidents / clean run": r["SARA_false_incidents"]["mean"],
                     "Calibrated SARA: over-delay (s)": r["SARA"]["over_delay"]["mean"]})
    return pd.DataFrame(rows), "ext_numbers.json → [B][cells][<cell>][SARA_recalibrated] (secondary result)"


def ext_c_clean_table(e: dict) -> tuple[pd.DataFrame, str]:
    c = e["C"]
    rows = []
    for lv, x in c["clean"].items():
        rows.append({"Cap": lv, "Cap (tx per node)": None if lv == "none" else c["caps"].get(lv),
                     "Runs with any eviction or rejection": x["share_with_drops"], "Evictions per run": x["evicted_mean"],
                     "Runs without drops": x["runs_without_drops"],
                     "… checked zero residue/EvDiv": x["runs_without_drops_checked_zero"],
                     "Runs with residue > 0": x["share_residue"], "Runs with EvDiv > 0": x["share_evdiv"],
                     "SARA false incidents / clean run": x["SARA_false_incidents"]["mean"]})
    return pd.DataFrame(rows), "ext_numbers.json → [C][clean][<cap level>]"


def ext_c_table(e: dict, level: str) -> tuple[pd.DataFrame, str]:
    c = e["C"]["disturbed"][level]
    rows = []
    for d in DISTS:
        x = c[d]
        row = {"Disturbance": LAB[d], "Evictions (B1 run)": x["B1"]["evicted"],
               "EvDiv +10 s (B1)": x["B1"]["evdiv_10"], "EvDiv +300 s (B1)": x["B1"]["evdiv_300"],
               "Lost tx at horizon (B1)": x["B1"]["lost_end"]}
        for p in ("B1", "B2", "SARA"):
            row[f"FRE_state {p} (s)"] = x[p]["FRE_state"]["mean"]
        for p in ("B1", "B2", "SARA"):
            row[f"Declared {p}"] = x[p]["declared_share"]
        row["SARA unrepairable gaps"] = x["SARA"].get("unrepairable")
        row["SARA reached HIGH"] = x["SARA"].get("reached_high")
        row["SARA over-delay (s)"] = x["SARA"]["over_delay"]
        rows.append(row)
    return pd.DataFrame(rows), f"ext_numbers.json → [C][disturbed][{level}][<disturbance>][<policy>]"


def discussion_limits(discussion: str) -> dict:
    """{'Extension A: …': '<the *Limits.* bullet>', …} from the discussion section of EXTENSIONS.md."""
    out, name, cur, grab = {}, None, [], False
    for ln in discussion.splitlines():
        m = re.match(r"^\*\*(Extension [ABC][^*]*|Common limitations)\.?\*\*", ln.strip())
        if m:
            if name and cur:
                out[name] = "\n".join(cur).strip()
            name, cur, grab = m.group(1).rstrip("."), [], False
            if name == "Common limitations":
                cur.append(ln.strip()[len(m.group(0)):].strip())
                grab = True
            continue
        if ln.startswith("- "):
            grab = ln.startswith("- *Limits.*")
            if grab:
                cur.append(ln[len("- *Limits.*"):].strip())
            continue
        if grab and ln.strip():
            cur.append(ln.strip())
    if name and cur:
        out[name] = "\n".join(cur).strip()
    return {k: " ".join(v.split("\n")) for k, v in out.items()}


# ------------------------------------------------------------------------------------------ method page
def readme_section(heading: str) -> str:
    return md_subsection(load_text("readme"), heading)


def module_docstring(rel: str) -> str:
    """The module docstring of a project file (read, not imported)."""
    p = ROOT / rel
    return ast.get_docstring(ast.parse(p.read_text(encoding="utf-8"))) or ""
