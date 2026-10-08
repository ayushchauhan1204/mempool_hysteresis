"""Study results: the frozen main study and, separately, the extension experiments. Stored files only."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from app_lib import plots as P
from app_lib import results_io as io
from app_lib import ui

ui.setup_page()
st.title("Study results")
st.caption("Read from stored files only: nothing is simulated or recomputed here. Every table names the file and key "
           "it was read from and can be downloaded as CSV.")


def pval(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def show(df: pd.DataFrame, src: str, name: str):
    df = df.copy()
    cfg = {}
    for c in df.columns:
        lc = c.lower()
        is_share = ("share" in lc or lc.startswith(("certified", "declared ", "runs with ", "sara reached"))) \
            and "(s)" not in lc
        if "p (holm)" in lc or lc.endswith(" p") or lc == "p":
            df[c] = df[c].map(pval)
        elif is_share and pd.api.types.is_numeric_dtype(df[c]):
            cfg[c] = st.column_config.NumberColumn(format="percent")
        elif pd.api.types.is_float_dtype(df[c]):
            cfg[c] = st.column_config.NumberColumn(format="%.2f")
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg)
    st.caption(f"Source: {src}")
    st.download_button("Download CSV", df.to_csv(index=False), file_name=f"{name}.csv", mime="text/csv", key=f"dl_{name}")


def image(path, caption):
    if path:
        st.image(str(path), caption=caption, width="stretch")
    else:
        st.info(f"Figure not found: {caption}")


main_tab, ext_tab = st.tabs(["Main study (held-out seeds 1000–1199)", "Extension experiments (reported separately)"])

# ===================================================================================================== main study
with main_tab:
    try:
        n = io.load_json("numbers")
        sw = io.load_json("sweeps")
        ver = io.load_json("verification")
    except io.ResultsMissing as e:
        st.error(str(e))
        st.stop()
    m = io.meta_summary(n)
    st.markdown(f"**Frozen main study.** Held-out seeds {m['seeds']} (n = {m['n_seeds']}), {m['runs']:,} simulation "
                f"runs, generated {m['generated']}. Calibration on dev seeds 0–4: tau_m {m['calibration']['tau_m']} s, "
                f"beta {m['calibration']['beta']:.2f} blocks. Paired two-sided Wilcoxon tests with Holm correction "
                "within each table; r = matched-pairs rank-biserial correlation.")
    tabs = st.tabs(["Headline", "Hysteresis", "SARA vs baselines", "Per disturbance", "Ablations", "Robustness sweeps",
                    "Post-hoc calibration check", "False alarms, downstream", "Hand verification", "Figures",
                    "RESULTS.md"])
    with tabs[0]:
        st.markdown("False-recovery exposure: seconds after the disturbance ended during which a policy reported "
                    "'recovered' while the true state had not recovered (FRE_state: residue remained).")
        show(*io.headline_table(n), "headline_false_recovery")
    with tabs[1]:
        st.markdown("Table I: the no-intervention network (B1), disturbed vs clean history.")
        show(*io.hysteresis_table(n), "table1_hysteresis")
    with tabs[2]:
        metric = st.selectbox("Metric", ["FRE_state", "FRE", "FRE_backlog", "over_delay", "T_conv", "T_decl",
                                         "residue_auc", "inband_kB", "unnecessary", "conf_lat_mean"], key="t2m")
        st.markdown("Table II: SARA minus each baseline (median paired difference).")
        show(*io.paired_table(n, metric), f"table2_{metric}")
    with tabs[3]:
        c1, c2 = st.columns(2)
        dist = c1.selectbox("Disturbance", io.DISTS, format_func=io.LAB.get, key="bd")
        stat = c2.selectbox("Statistic", ["mean", "median", "q25", "q75", "max"], key="bs")
        show(*io.breakdown_table(n, dist, stat), f"descriptive_{dist}_{stat}")
    with tabs[4]:
        metric = st.selectbox("Metric", ["FRE_state", "FRE", "T_conv", "inband_kB", "resid_at_decl", "over_delay",
                                         "unnecessary", "reopened", "FRE_backlog"], key="t3m")
        st.markdown("Table III: full SARA against each ablation variant (−D no divergence detection, −R no risk "
                    "assessment, −V no recovery verification).")
        show(*io.ablation_table(n, metric), f"table3_{metric}")
    with tabs[5]:
        name = st.selectbox("Sweep", io.sweep_names(sw), format_func=lambda k: sw[k]["title"], key="sw")
        b = sw[name]
        st.markdown(f"**{b['title']}** ({', '.join(b['dists'])}), seeds 2000–2049; per-seed means with stored 95% CIs.")
        st.plotly_chart(P.sweep_figure(io.sweep_long(sw, name), b["xlabel"]), width="stretch")
        show(*io.sweep_table(sw, name), f"sweep_{name}")
        if b.get("calibration"):
            st.caption("Recalibrated on dev seeds per point: " + "; ".join(
                f"{k}: beta {v['beta']:.2f}, tau_m {v['tau_m']}" for k, v in b["calibration"].items()))
    with tabs[6]:
        st.warning("**Post hoc, not pre-specified.** Added after the held-out run showed false incidents in clean runs. "
                   "The main results keep the pre-specified 5-seed calibration.")
        show(*io.calibration_check_table(sw), "posthoc_calibration_check")
    with tabs[7]:
        st.markdown("False incidents in clean runs:")
        show(*io.false_alarms_table(n), "false_alarms_clean")
        st.markdown("Downstream effect on the identical post-recovery workload vs the clean history:")
        show(*io.downstream_table(n), "downstream_by_policy")
    with tabs[8]:
        st.markdown(f"Seed {ver['seed']}, {ver['dist']}, B1: residue recomputed from raw state dumps and FRE_state from "
                    "the raw monitor log with deliberately naive code (experiments/verify_by_hand.py).")
        show(*io.verification_table(ver), "verification")
    with tabs[9]:
        for name, cap in io.MAIN_FIGURES:
            image(io.figure(name), cap)
    with tabs[10]:
        try:
            txt = io.load_text("results_md")
            st.download_button("Download RESULTS.md", txt, file_name="RESULTS.md", mime="text/markdown")
            st.markdown(txt)
        except io.ResultsMissing as e:
            st.error(str(e))

# ===================================================================================================== extensions
with ext_tab:
    st.info("**Extension experiments, reported separately.** They never change, replace or re-tune the main study: "
            "every new model feature is off by default, and with defaults every run is bit-for-bit identical to the "
            "main study's (regression snapshot test). Definitions, hypotheses, seeds and configurations were "
            "pre-registered in results/extensions/EXTENSIONS.md before any extension run.")
    try:
        e = io.load_json("ext_numbers")
        secs = io.md_sections(io.load_text("extensions_md"))
    except io.ResultsMissing as err:
        st.error(str(err))
        st.stop()
    pr = e.get("preregistration", {})
    st.caption(f"Generated {e.get('generated')} by experiments/ext_analyze.py. Pre-registration section unchanged since "
               f"it was recorded: {pr.get('unchanged')} (sha256 {str(pr.get('sha256'))[:16]}…).")
    etabs = st.tabs(["Key findings", "A: confirmation delay", "B: scale and topology", "C: bounded mempools",
                     "Hand verification", "Discussion and limitations", "Pre-registration and change log"])
    with etabs[0]:
        for ext, lines in e.get("key_findings", {}).items():
            st.markdown(f"**Extension {ext}**")
            for ln in lines:
                st.markdown(f"- {ln}")
        st.caption("Generated statements: every number is filled in by code from ext_numbers.json.")
    with etabs[1]:
        a = e["A"]
        rp = a["reproduction"]
        st.markdown(f"Do residue and backlog debt delay users, and does a policy that certifies recovery falsely also "
                    f"leave users worse off? Re-measured runs reproduce the stored main-study metrics: "
                    f"**{rp['all_identical']}** ({rp['found']} of {rp['runs']} runs).")
        sample = st.radio("Seeds", ["heldout", "replication"], horizontal=True, key="ea_s",
                          format_func=lambda s: "held-out 1000–1199 (the main study's runs)" if s == "heldout"
                          else "replication 3000–3099")
        st.markdown("Primary outcome: per-run mean excess confirmation delay of the shared workload created in the "
                    "120 s before to 300 s after the disturbance, disturbed minus paired clean history (s).")
        show(*io.ext_a_table(e, sample), f"ext_a_primary_{sample}")
        st.markdown("Medians per run by creation window, block-composition distance and FRE_state:")
        show(*io.ext_a_windows_table(e, sample), f"ext_a_windows_{sample}")
        st.markdown("Spearman ρ between FRE_state and the primary outcome across runs (unadjusted p):")
        show(*io.ext_a_spearman_table(e, sample), f"ext_a_spearman_{sample}")
        image(io.figure("ext_a_excess_delay", ext=True), "Extension A: excess confirmation delay (held-out seeds)")
    with etabs[2]:
        st.markdown("Do the findings hold beyond one 10-node random regular graph? Partition in every cell; isolation "
                    "and asymmetric link only in the 10- and 20-node cells (scope change for compute time, logged "
                    "before any result was looked at). SARA keeps its calibrated values.")
        show(*io.ext_b_table(e), "ext_b_partition_cells")
        st.markdown("Isolation and asymmetric link (10- and 20-node cells):")
        show(*io.ext_b_other_table(e), "ext_b_isolation_asymmetric")
        st.markdown("**Secondary result:** SARA re-calibrated with the Phase 3 rule on dev seeds for three 50-node cells.")
        show(*io.ext_b_recal_table(e), "ext_b_recalibrated")
        image(io.figure("ext_b_fre_state", ext=True), "Extension B: FRE_state after a partition per cell")
        image(io.figure("ext_b_sara_costs", ext=True), "Extension B: SARA's false incidents and over-delay per cell")
    with etabs[3]:
        c = e["C"]
        st.markdown(f"Can eviction leave divergence that neither gossip nor SARA can repair? Caps from clean dev-seed "
                    f"backlog (largest per-node mempool M = {c['M']}): "
                    + ", ".join(f"{k} {v}" for k, v in c["caps"].items()) + " transactions per node.")
        st.markdown("Clean histories:")
        show(*io.ext_c_clean_table(e), "ext_c_clean")
        level = st.radio("Cap level", list(c["disturbed"]), horizontal=True, key="ec_l")
        show(*io.ext_c_table(e, level), f"ext_c_{level}")
        st.markdown("SARA minus baseline on FRE_state:")
        show(*io.ext_c_paired_table(e, level), f"ext_c_paired_{level}")
        image(io.figure("ext_c_capacity", ext=True), "Extension C: bounded mempools")
    with etabs[4]:
        try:
            v = io.load_json("ext_verification")
            st.markdown("Recomputed with deliberately naive code (experiments/ext_verify_by_hand.py).")
            show(*io.ext_verification_table(v), "verification_ext")
        except io.ResultsMissing as err:
            st.error(str(err))
    with etabs[5]:
        st.markdown(secs.get("discussion", "Not found in EXTENSIONS.md."))
    with etabs[6]:
        st.markdown(secs.get("changelog", ""))
        with st.expander("Pre-registration (verbatim)"):
            st.markdown(secs.get("preregistration", ""))
        with st.expander("Generated results section of EXTENSIONS.md (verbatim)"):
            st.markdown(io.without_images(secs.get("results", "")))
