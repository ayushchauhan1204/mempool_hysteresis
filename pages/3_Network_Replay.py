"""Network replay: the nodes, links and residue of one run over time.

After a new run the slider view plays back (app_lib/playback.py): the time slider advances by itself through the
stored snapshots and everything below it follows. Display only; Pause hands the slider back to you."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app_lib import palette as C
from app_lib import playback as PB
from app_lib import plots as P
from app_lib import runs as R
from app_lib import ui
from app_lib import snapshots as S

ui.setup_page()
sel = ui.sidebar()
st.title("Network replay")
st.caption("The run is simulated once with a read-only snapshot every few simulated seconds (taken just after the "
           "evaluator's own sample). Residue per frame uses the evaluator's definition, so it matches the residue "
           "series of the Simulator page at the same instants. Link states come from the disturbance description.")
try:
    ov = sel.overrides()
except ValueError as e:
    st.error(f"Invalid settings: {e}")
    st.stop()
cfg = R.make_config(ov)
if ov:
    st.warning(f"**{R.EXPLORATORY}.** {R.describe_overrides(ov, cfg)}")
else:
    st.info("Study settings (calibrated configuration). " + R.seed_note(sel.seed))

c1, c2, c3 = st.columns([3, 1.2, 1.4])
qp_policy = st.query_params.get("policy")
policy = c1.radio("Policy", R.POLICIES, horizontal=True, format_func=R.POLICY_LABEL.get, key="rp_policy",
                  index=R.POLICIES.index(qp_policy) if qp_policy in R.POLICIES else 0,
                  help="Same history, different policy: compare B1 doing nothing with SARA reconciling.")
interval = c2.selectbox("Snapshot every", [2.0, 5.0, 10.0], index=1, format_func=lambda v: f"{v:g} s")
mode = c3.radio("View", ["Slider", "Animation"], horizontal=True,
                help="Slider: one frame at a time (default). Animation: play/pause in the browser.")
try:
    with st.spinner("Simulating with snapshots …"):
        rp = S.replay(sel.seed, sel.dist, policy, ov, interval)
except Exception as e:
    st.error(f"The replay failed: {e}")
    st.stop()

theme = C.current_mode()
te = rp["t_end"]
frames = rp["frames"]
times = [f["t"] - te for f in frames]
d = rp["disturbance"]
what = {"partition": f"minority side {d['group_a']}", "isolation": f"isolated node(s) {d['nodes']}",
        "loss": f"lossy links of nodes {d['nodes']}", "latency": f"slow links of nodes {d['nodes']}",
        "asymmetric": f"outbound traffic of nodes {d['nodes']} blackholed",
        "burst": "transaction burst (no link changes)"}[sel.dist]
st.caption(f"{R.DIST_LABEL[sel.dist]} from t = {d['start']:.0f} s to {d['end']:.0f} s: {what}. Ringed nodes are the "
           f"disturbance's targets. {rp['n']} nodes, {len(rp['edges'])} links.")

if mode == "Animation":
    step = max(1, len(frames) // 60)
    st.plotly_chart(P.animated_network(rp, step, theme), width="stretch")
    st.caption(f"{len(range(0, len(frames), step))} frames, every {interval * step:g} s. Use the slider view for the "
               "per-node table and events.")
    st.plotly_chart(P.replay_strip(rp, 0, theme), width="stretch")
    st.stop()

# ----------------------------------------------------------------------------- playback over the stored snapshots
SLIDER = "rp_k"
default = min(range(len(times)), key=lambda k: abs(times[k] - 10.0))
idx = PB.frame_indices(len(frames))                      # the snapshots playback steps through (first and last)
pb = PB.state("rp", (sel.seed, sel.dist, policy, ov, interval, ui.applied()), len(idx))
if pb["fresh"] or st.session_state.get(SLIDER) not in range(len(frames)):
    st.session_state[SLIDER] = default                   # a new run without playback opens at +10 s, as before
    pb["fresh"] = False
if pb["finished"]:
    st.session_state[SLIDER] = len(frames) - 1           # playback ran (or was skipped) to the end
    pb["finished"] = False
if pb["status"] == "paused":
    st.session_state[SLIDER] = idx[pb["pos"]]
status_ph = PB.controls("rp", pb)

slider_label = "Time since the disturbance ended (s)"
slider_ph = st.empty()
left, right = st.columns([3, 2])
with left:
    graph_slots = PB.swap_slots("rp")                    # two stacked slots: each redraw happens behind the other
info_ph = right.empty()
st.markdown("**Per node at this frame**"
            + (" (evicted / rejected: distinct transactions so far)" if "evicted" in frames[0] else ""))
nodes_ph = st.empty()
events_ph = st.empty()
strip_box = PB.chart_box("rp")
with st.expander("All events up to this frame"):
    allev_ph = st.empty()
shown = {}


def frame_view(k: int, live: bool, slot: int | None = None) -> None:
    """Everything below the slider for snapshot k. live: during playback (and paused), the residue strip shows the
    run up to k only. slot: while playing, the graph goes to alternate stacked slots, on an opaque background."""
    f = frames[k]
    phase = "before the disturbance" if f["t"] < d["start"] else ("during the disturbance" if f["t"] < d["end"] else
                                                                   "after the disturbance")
    graph = P.network_figure(rp, k, theme)
    if slot is None:
        graph_slots[0].plotly_chart(graph, width="stretch", theme=None)
        graph_slots[1].empty()
    else:
        graph.update_layout(paper_bgcolor=C.CHROME[theme]["surface"])
        graph_slots[slot % 2].plotly_chart(graph, width="stretch", theme=None)
    with info_ph.container():
        st.markdown(f"**t = {f['t']:.0f} s** ({times[k]:+.0f} s from the disturbance end), {phase}")
        res = "not counted yet (the evaluator starts 60 s before the disturbance ends)" if f["residue"] is None \
            else f"{f['residue']} transactions"
        st.markdown(f"- True residue: **{res}**")
        st.markdown(f"- {policy} reports: **{f['status']}**" + (f" (risk tier {f['tier']})" if f["tier"] else ""))
        st.markdown(f"- Connectivity monitor: {len(f['monitor_unhealthy'])} link(s) flagged unhealthy")
        st.markdown(f"- Chain: {'tips on one chain' if f['chain_ok'] else 'tips on different branches'}; "
                    f"{f['mined']} blocks mined, {f['reorgs']} reorgs so far")
        if "evicted" in f:
            st.markdown(f"- Mempool cap {rp['mempool_cap']}: {sum(f['evicted'])} evicted and {sum(f['rejected'])} "
                        f"rejected so far" + (f"; SARA unrepairable gaps {f['unrepairable']}"
                                              if f.get("unrepairable") is not None else ""))
        if f["residue_ids"]:
            st.caption("Residue transaction ids (first 30): " + ", ".join(str(x) for x in f["residue_ids"][:30])
                       + (" …" if len(f["residue_ids"]) > 30 else ""))

    nodes = pd.DataFrame({"node": range(rp["n"]), "pending": f["pending"], "share": f["share"],
                          "residue lacked": f["lacks"], "residue held": f["holds"], "tip height": f["heights"]})
    if "evicted" in f:
        nodes["evicted"] = f["evicted"]
        nodes["rejected"] = f["rejected"]
        nodes["minimum fee"] = f["min_fee"]
    nodes_ph.dataframe(nodes, hide_index=True, width="stretch", height=min(420, 38 + 35 * rp["n"]), column_config={
        "share": st.column_config.NumberColumn("share of pending", format="percent"),
        "minimum fee": st.column_config.NumberColumn(format="%.2f")})

    prev_t = frames[k - 1]["t"] if k > 0 else f["t"] - interval
    ev = S.events_between(rp, prev_t, f["t"])
    with events_ph.container():
        st.markdown(f"**Events since the previous frame** (t = {prev_t:.0f} s to {f['t']:.0f} s)")
        if ev:
            st.dataframe(pd.DataFrame([(t - te, kind, text) for t, kind, text in ev],
                                      columns=["t − t_end (s)", "kind", "event"]), hide_index=True, width="stretch",
                         column_config={"t − t_end (s)": st.column_config.NumberColumn(format="%+.1f")})
        else:
            st.caption("No block, reorg, policy, monitor or eviction events in this interval.")
    if live and "strip_clock" in shown:                  # the whole run, covered beyond snapshot k
        PB.show_clock(shown["strip_clock"], times[k], shown, pb, moving=False)
    elif live:
        shown["strip_clock"] = PB.chart_with_clock(
            "rp", PB.cached_figure("rp", (pb["key"], theme), lambda: P.replay_strip(rp, None, theme)), times[k],
            shown, pb, box=strip_box, moving=False)
    else:                                                # as before playback existed: frame k marked
        PB.chart_with_clock("rp", P.replay_strip(rp, k, theme), None, shown, box=strip_box)
    allev = S.events_between(rp, -1.0, f["t"])
    allev_ph.dataframe(pd.DataFrame([(t - te, kind, text) for t, kind, text in allev],
                                    columns=["t − t_end (s)", "kind", "event"]), hide_index=True, width="stretch",
                       height=360, column_config={"t − t_end (s)": st.column_config.NumberColumn(format="%+.1f")})


def render(pos: int) -> None:
    """Playback frame pos: the slider (moved by the playback, not draggable meanwhile) and the view below it."""
    k = idx[pos]
    PB.show_status(status_ph, pb, f"{times[k]:+.0f} s", shown)
    slider_ph.select_slider(slider_label, options=list(range(len(frames))), value=k, disabled=True,
                            format_func=lambda i: f"{times[i]:+.0f}")
    frame_view(k, live=True, slot=pos)


if pb["status"] == "playing":
    render(pb["pos"])
else:
    PB.show_status(status_ph, pb, f"{times[st.session_state[SLIDER]]:+.0f} s", shown)
    choice = slider_ph.select_slider(slider_label, options=list(range(len(frames))), key=SLIDER,
                                     format_func=lambda k: f"{times[k]:+.0f}", on_change=PB.stop, args=("rp",))
    frame_view(int(choice), live=pb["status"] == "paused")
PB.loop("rp", pb, render)
