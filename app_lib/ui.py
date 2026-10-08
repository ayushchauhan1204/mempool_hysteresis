"""Shared page setup and the run-settings sidebar of the live pages.

Each live page calls ``setup_page()`` and ``sidebar()`` itself, so the sidebar is there whether the page was reached
through app.py's navigation or opened directly (Streamlit also serves the files in pages/ on their own, for example
when a deep link is the first request after the server starts).
"""
from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitAPIException

from . import results_io as io
from . import runs as R
from . import style


def setup_page():
    """Wide layout. app.py sets it already when it routes; a page opened directly sets it here. Then the shared
    look (rounded corners, theme helper; app_lib/style.py)."""
    try:
        st.set_page_config(page_title="Mempool hysteresis", page_icon=":material/hub:", layout="wide")
    except StreamlitAPIException:
        pass
    style.apply()


def applied() -> int:
    """How many times the run settings were applied this session (part of each playback's run key)."""
    return st.session_state.get("applied", 0)


def selection_from_query():
    """Optional deep link, e.g. ?dist=loss&seed=1002&cap=loose&topology=watts_strogatz&nodes=20&degree=4&rate=8.
    Applied once per distinct link; the sidebar then shows (and can change) the same settings."""
    qp = st.query_params
    keys = ("dist", "seed", "cap", "topology", "nodes", "degree", "rate")
    if not any(k in qp for k in keys):
        return
    key = tuple((k, qp.get(k)) for k in keys)
    if st.session_state.get("_deep_link") == key:
        return
    st.session_state["_deep_link"] = key
    base = R.base_config()
    presets = io.cap_presets()
    try:
        raw = {}
        if "topology" in qp:
            raw["topology"] = qp["topology"]
        if "nodes" in qp:
            raw["n_nodes"] = int(qp["nodes"])
        if "degree" in qp:
            raw["degree"] = int(qp["degree"])
        if "rate" in qp:
            raw["tx_rate"] = float(qp["rate"])
            raw["block_capacity"] = R.scaled_capacity(raw["tx_rate"], base)
        if "cap" in qp:
            raw["mempool_cap"] = presets[qp["cap"]] if qp["cap"] in presets else int(qp["cap"])
            st.session_state.setdefault("ui", {"hold": True, "cap_choice": "off"})["cap_choice"] = \
                qp["cap"] if qp["cap"] in presets else "custom"
        dist = qp.get("dist", "partition")
        if dist not in R.DISTURBANCES:
            raise ValueError(f"unknown disturbance {dist!r}")
        for d in R.DISTURBANCES:
            R.normalize_overrides(d, raw, base)
        st.session_state["selection"] = R.Selection(dist, int(qp.get("seed", R.DEFAULT_SEED)),
                                                     tuple(sorted(raw.items())))
    except (ValueError, KeyError) as e:
        st.sidebar.error(f"Link settings not applied: {e}")


def sidebar() -> R.Selection:
    """Render the run-settings form (applied with one button) and return the applied selection."""
    selection_from_query()
    base = R.base_config()
    sel = R.current_selection()
    raw = dict(sel.raw_overrides)
    ui = st.session_state.setdefault("ui", {"hold": True, "cap_choice": "off"})
    presets = io.cap_presets()
    with st.sidebar.form("run_settings"):
        st.markdown("#### Run settings")
        dist = st.selectbox("Disturbance", R.DISTURBANCES, index=R.DISTURBANCES.index(sel.dist),
                            format_func=R.DIST_LABEL.get)
        seed = st.number_input("Seed", min_value=0, max_value=10 ** 9, value=int(sel.seed), step=1,
                               help="Default 1000 (held-out). Seeds 0–4 were used for calibration.")
        model_changed = any(k in R.MODEL_PARAMS for k, _ in sel.overrides())
        with st.expander("Model (extensions B and C)", expanded=model_changed):
            topo = st.selectbox("Topology", list(R.TOPOLOGY_LABEL),
                                index=list(R.TOPOLOGY_LABEL).index(raw.get("topology", base.topology)),
                                format_func=R.TOPOLOGY_LABEL.get)
            n_nodes = st.number_input("Nodes", min_value=4, max_value=R.MAX_NODES, step=1,
                                      value=int(raw.get("n_nodes", base.n_nodes)),
                                      help=f"Up to {R.MAX_NODES}; more than {R.SLOW_NODES} nodes makes a run much slower.")
            degree = st.number_input("Degree", min_value=2, max_value=12, step=1, value=int(raw.get("degree", base.degree)),
                                     help="Expected degree for Erdős–Rényi; must be even for Watts–Strogatz.")
            tx_rate = st.number_input("Transaction rate (tx/s)", min_value=0.5, max_value=20.0, step=0.5,
                                      value=float(raw.get("tx_rate", base.tx_rate)))
            hold = st.checkbox("Hold block-space utilisation (scale block capacity with the rate, as in "
                               "extension B)", value=ui["hold"])
            cap_in = st.number_input("Block capacity (tx), used when utilisation is not held", min_value=10,
                                     max_value=2000, step=10, value=int(raw.get("block_capacity", base.block_capacity)))
            options = ["off"] + list(presets) + ["custom"]
            choice = ui["cap_choice"] if ui["cap_choice"] in options else "off"
            cap_choice = st.selectbox(
                "Mempool capacity", options, index=options.index(choice),
                format_func=lambda o: ("off: unlimited (study setting)" if o == "off" else "custom" if o == "custom"
                                       else f"{o}: {presets[o]} tx per node (extension C level)"))
            cap_custom = st.number_input("Custom mempool capacity (tx per node)", min_value=20, max_value=10000,
                                         step=10, value=int(raw.get("mempool_cap") or presets.get("loose", 500)))
        dist_changed = any(k in R.DIST_PARAMS for k, _ in sel.overrides())
        with st.expander("Disturbance parameters", expanded=dist_changed):
            dvals = {}
            for k, spec in R.DIST_PARAMS.items():
                dvals[k] = st.number_input(spec["label"], min_value=float(spec["min"]), max_value=float(spec["max"]),
                                           step=float(spec["step"]), value=float(raw.get(k, getattr(base, k))),
                                           help="Applies to: " + ", ".join(R.DIST_LABEL[d] for d in spec["dists"]))
        submitted = st.form_submit_button("Apply", type="primary", width="stretch")
    if submitted:
        new_raw = dict(topology=topo, n_nodes=int(n_nodes), degree=int(degree), tx_rate=float(tx_rate),
                       block_capacity=R.scaled_capacity(tx_rate, base) if hold else int(cap_in),
                       mempool_cap=None if cap_choice == "off" else
                       (presets[cap_choice] if cap_choice in presets else int(cap_custom)), **dvals)
        try:
            for d in R.DISTURBANCES:
                R.normalize_overrides(d, new_raw, base)
        except ValueError as e:
            st.sidebar.error(f"Not applied: {e}.")
        else:
            st.session_state["selection"] = R.Selection(dist, int(seed), tuple(sorted(new_raw.items())))
            st.session_state["applied"] = st.session_state.get("applied", 0) + 1     # every Apply replays the run
            ui.update(hold=hold, cap_choice=cap_choice)
    sel = R.current_selection()
    ov = sel.overrides()
    cfg = R.make_config(ov)
    if ov:
        st.sidebar.warning(f"**{R.EXPLORATORY}.** " + R.describe_overrides(ov, cfg))
    else:
        st.sidebar.success("Study settings (calibrated configuration).")
    st.sidebar.caption(R.seed_note(sel.seed))
    if sel.ignored():
        st.sidebar.caption("Not used for this disturbance: " + ", ".join(R.DIST_PARAMS[k]["label"] for k in sel.ignored()))
    if cfg.n_nodes > R.SLOW_NODES:
        st.sidebar.caption(f"{cfg.n_nodes} nodes: each run takes much longer (about a minute at 50).")
    return sel
