"""Mempool hysteresis: local Streamlit frontend.

    streamlit run app.py          # from the project root

This entrypoint routes to the pages in pages/ and renders the overview. The live pages (Simulator, Policy
comparison, Network replay) run the real simulator (mh/) through app_lib and render the shared run-settings sidebar
themselves (app_lib/ui.py); the study pages only read stored results.
"""
from __future__ import annotations

import streamlit as st

from app_lib import results_io as io
from app_lib import runs as R
from app_lib import style

st.set_page_config(page_title="Mempool hysteresis", page_icon=":material/hub:", layout="wide")


def overview():
    style.apply()                    # the pages in pages/ apply it through ui.setup_page()
    st.title("Mempool hysteresis and the SARA recovery audit")
    try:
        readme = io.load_text("readme")
        intro = readme.split("## Quick start")[0].split("\n", 1)[1].strip()
        st.markdown(intro)
    except io.ResultsMissing as e:
        st.warning(str(e))
    st.subheader("Pages")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Live simulation** (runs the real simulator, about a second per run at study settings)")
        st.page_link("pages/1_Simulator.py", label="Simulator: one disturbance under one policy", icon=":material/play_circle:")
        st.page_link("pages/2_Policy_Comparison.py", label="Policy comparison: B1 vs B2 vs SARA on one seed",
                     icon=":material/compare_arrows:")
        st.page_link("pages/3_Network_Replay.py", label="Network replay: the nodes, links and residue over time",
                     icon=":material/hub:")
    with c2:
        st.markdown("**Stored results** (read from files, nothing is re-run)")
        st.page_link("pages/4_Study_Results.py", label="Study results: the 200-seed study and the extensions",
                     icon=":material/table_chart:")
        st.page_link("pages/5_Method.py", label="Method: model, ground truth, policies, limitations",
                     icon=":material/menu_book:")
    st.subheader("Study settings")
    cfg = R.base_config()
    st.caption("The calibrated configuration every live run starts from (mh.calibration.load_config()). The sidebar "
               "on the live pages changes a copy; any change makes a run exploratory, not part of the study.")
    rows = [("Nodes / degree / topology", f"{cfg.n_nodes} / {cfg.degree} / {R.TOPOLOGY_LABEL[cfg.topology]}"),
            ("Transactions", f"{cfg.tx_rate:g} tx/s, fee ~ lognormal(0, {cfg.fee_sigma:g})"),
            ("Blocks", f"mean {cfg.block_interval:g} s, {cfg.block_capacity} tx per block"),
            ("Disturbance", f"from {cfg.dist_start:g} s for {cfg.dist_duration:g} s (burst {cfg.burst_duration:g} s); "
                            f"run ends at {cfg.horizon:g} s"),
            ("Mempool capacity", "unlimited" if cfg.mempool_cap is None else str(cfg.mempool_cap)),
            ("SARA calibration (dev seeds 0–4)", f"tau_m {cfg.tau_m:g} s, eps_D {cfg.eps_D:g}, beta {cfg.beta:.2f} "
                                                 f"blocks, eps_size {cfg.eps_size:g}")]
    st.table({"Setting": [r[0] for r in rows], "Value": [r[1] for r in rows]})
    st.subheader("Stored results")
    files = [("results/numbers.json", "numbers"), ("results/sweeps.json", "sweeps"),
             ("results/verification.json", "verification"), ("results/extensions/ext_numbers.json", "ext_numbers"),
             ("results/extensions/EXTENSIONS.md", "extensions_md")]
    st.table({"File": [f for f, _ in files],
              "Status": ["present" if io.FILES[k].exists() else f"missing: run {io.GENERATOR[k]}" for _, k in files]})


pages = {
    "": [st.Page(overview, title="Overview", icon=":material/home:", default=True)],
    "Live simulation": [
        st.Page("pages/1_Simulator.py", title="Simulator", icon=":material/play_circle:"),
        st.Page("pages/2_Policy_Comparison.py", title="Policy comparison", icon=":material/compare_arrows:"),
        st.Page("pages/3_Network_Replay.py", title="Network replay", icon=":material/hub:"),
    ],
    "Stored results": [
        st.Page("pages/4_Study_Results.py", title="Study results", icon=":material/table_chart:"),
        st.Page("pages/5_Method.py", title="Method", icon=":material/menu_book:"),
    ],
}
st.navigation(pages).run()
