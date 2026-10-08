"""Simulator: one disturbance under one policy, run live with the real simulator.

After a new run the result plays back (app_lib/playback.py): the charts draw in over time and the metric cards,
verdict and audit trail fill in as the playback clock passes each event. Display only; the last frame is the
static result."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app_lib import palette as C
from app_lib import playback as PB
from app_lib import plots as P
from app_lib import runs as R
from app_lib import ui

ui.setup_page()
sel = ui.sidebar()
st.title("Simulator")
st.caption("Runs mh.runner.run_one exactly as demo.py does: the clean B1 history first (the backlog "
           "counterfactual), then the disturbed run. Settings are in the sidebar.")

qp_policy = st.query_params.get("policy")
policy = st.radio("Policy", R.POLICIES, horizontal=True, format_func=R.POLICY_LABEL.get, key="sim_policy",
                  index=R.POLICIES.index(qp_policy) if qp_policy in R.POLICIES else 0)
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

try:
    with st.spinner(f"Simulating {R.DIST_LABEL[sel.dist].lower()}, seed {sel.seed}, {policy} …"):
        run = R.policy_run(sel.seed, sel.dist, policy, ov)
except Exception as e:                       # e.g. no connected graph could be drawn for these settings
    st.error(f"The run failed: {e}")
    st.stop()

m = run["metrics"]
theme = C.current_mode()
run_key = (sel.seed, sel.dist, policy, ov, ui.applied())
window = P.x_range(run)
clocks = PB.clocks(*window)
pb = PB.state("sim", run_key, len(clocks))
pos0 = PB.position(pb)
shown = {}                                   # what each placeholder shows now (only changes are sent)


def where(clock):
    return "the end of the run" if clock is None else f"{clock:+.0f} s"


status_ph = PB.controls("sim", pb)
PB.show_status(status_ph, pb, where(clocks[pos0]), shown)
st.code(run["describe"], language=None)


def draw_verdict(clock):
    verdict = R.verdict(m) if PB.revealed(PB.verdict_time(m), clock) else None
    if shown.get("verdict", 0) != verdict:
        verdict_ph.markdown(f"**Verdict for {policy}.** "
                            + (verdict or ":gray[Pending until the events it describes have happened.]"))
        shown["verdict"] = verdict


verdict_ph = st.empty()
draw_verdict(clocks[pos0])

# ----------------------------------------------------------------------------- metric cards (demo.py strings)
row = R.outcome_row(m)
reveal = PB.reveal_times(m, run["t_end"] - run["dist_start"])
cards = [
    ("Detected", "detected", "First alarm, seconds after the disturbance started."),
    ("Declared recovered", "declared", "Final recovery declaration, seconds after the disturbance ended."
                                       + (" Not declared by the end of the run." if m["decl_censored"] else "")),
    ("State converged", "state ok", "Residue zero (and tips on one chain) for 10 s, seconds after the "
                                    "disturbance ended." + (" Not reached by the end of the run (censored)."
                                                            if m["conv_censored"] else "")),
    ("Backlog recovered", "backlog ok", "Pending set no larger than the clean history's for 10 s."
                                        + (" Not reached by the end of the run." if m["bk_censored"] else "")),
    ("FRE_state", "FRE_state", "Seconds the policy reported 'recovered' while residue remained."),
    ("FRE", "FRE", "Seconds it reported 'recovered' while residue or backlog debt remained."),
    ("Residue at declaration", "residue@decl", "Residue transactions when recovery was declared."),
    ("Recovery traffic", "traffic", "In-band recovery traffic (announce/request 36 B per id, 250 B per tx)."),
]


def draw_cards(clock):
    values = PB.masked_row(row, reveal, clock)
    if shown.get("cards") != values:
        with cards_ph.container():
            for chunk in (cards[:4], cards[4:]):
                cols = st.columns(4)
                for col, (label, k, help_) in zip(cols, chunk):
                    col.metric(label, values[k], help=help_)
        shown["cards"] = values


cards_ph = st.empty()
draw_cards(clocks[pos0])
st.caption("Same values and formatting as `python demo.py`. Times after the disturbance ended unless stated; "
           "'never' = not reached before the run ended.")
censored = [name for name, flag in (("Declared recovered", m["decl_censored"]), ("State converged", m["conv_censored"]),
                                    ("Backlog recovered", m["bk_censored"])) if flag]


def draw_censored(clock):
    show = bool(censored) and clock is None              # known only at the end of the run
    if shown.get("censored") != show:
        if show:
            censored_ph.warning(f"Not reached by the end of the run: {', '.join(censored)}. The value shown is the "
                                f"censoring time (the end of the run), as demo.py prints it.")
        else:
            censored_ph.empty()
        shown["censored"] = show


censored_ph = st.empty()
draw_censored(clocks[pos0])

st.subheader("What was true, and what the policy believed")
clock_ph = PB.chart_with_clock("sim", PB.cached_figure("sim", (run_key, theme), lambda: P.run_figure(run, theme)),
                               clocks[pos0], shown, pb, pos0, window[1])

# ----------------------------------------------------------------------------- Extension A
st.subheader("Effect on users: confirmation delay (extension A metrics)")
st.markdown(R.harm_line(run))
a = run["ext_a"]
rows = []
for w, name in (("before", "120 s before"), ("during", "during"), ("after", "300 s after"), ("exposed", "all three")):
    d, x = a[w]["delay"], a[w]["excess"]
    rows.append({"Created": name, "Transactions": d["n"], "Mean delay (s)": d["mean"], "Median (s)": d["median"],
                 "p95 (s)": d["p95"], "Never confirmed": d["never"], "Mean excess vs clean (s)": x["mean"],
                 "Share delayed": x["share_delayed"], "Confirmed in clean only": x["never_extra"]})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
    "Mean delay (s)": st.column_config.NumberColumn(format="%.1f"), "Median (s)": st.column_config.NumberColumn(format="%.1f"),
    "p95 (s)": st.column_config.NumberColumn(format="%.1f"),
    "Mean excess vs clean (s)": st.column_config.NumberColumn(format="%.2f"),
    "Share delayed": st.column_config.NumberColumn(format="percent")})
b = a["blocks"]
st.caption(f"Shared-workload transactions only (identical in both histories). Delay = mining time of the including "
           f"block on the final best chain minus creation time; excess censors unconfirmed transactions at the end of "
           f"the run (a lower bound). Blocks mined in the 300 s after the disturbance: composition distance "
           f"{b['bcd']:.3f} against the clean history ({b['displaced']} transactions the clean history confirmed there "
           f"are missing, {b['added']} added)."
           + (f" Burst extras: {a['burst_extra']['n']}, of which {a['burst_extra']['never']} never confirmed."
              if a["burst_extra"]["n"] else ""))
st.plotly_chart(P.delay_figure({policy: run}, mode=theme), width="stretch", theme=None)

# ----------------------------------------------------------------------------- Extension C
if run["mempool_cap"] is not None:
    st.subheader(f"Bounded mempools: {run['mempool_cap']} transactions per node (extension C metrics)")
    c = run["ext_c"]
    cols = st.columns(5)
    cols[0].metric("Evicted", f"{c['evicted']}", help="Evictions in this run (all nodes).")
    cols[1].metric("Rejected", f"{c['rejected']}", help="Arrivals refused: below the node's minimum fee or mempool full.")
    cols[2].metric("Evicted-divergence +10 s", f"{c['evdiv_10']:.0f}",
                   help="Residue candidates some node lacks because it evicted or rejected them, 10 s after the end.")
    cols[3].metric("… at +300 s", f"{c['evdiv_300']:.0f}")
    cols[4].metric("Lost at the end", f"{c['lost_end']:.0f}", help="Dropped somewhere, now pending nowhere and unconfirmed.")
    if policy.startswith("SARA"):
        st.caption(f"SARA marked {c['unrepairable']} (node, transaction) gaps unrepairable after a refused delivery and "
                   f"never pulled them again; refused deliveries in the run: {c['refused_deliveries']}.")
    st.dataframe(pd.DataFrame(run["node_drops"]), hide_index=True, width="stretch",
                 column_config={"min_fee": st.column_config.NumberColumn("minimum fee", format="%.2f")})

# ----------------------------------------------------------------------------- audit trail
st.subheader("Audit trail")
trail_all = R.audit_trail(run)


def draw_trail(clock):
    trail = PB.rows_until(trail_all, clock)
    if shown.get("trail") != len(trail):
        trail_ph.dataframe(pd.DataFrame(trail, columns=["t − t_end (s)", "entry"]), hide_index=True, width="stretch",
                           height=min(400, 38 + 35 * max(1, len(trail_all))),
                           column_config={"t − t_end (s)": st.column_config.NumberColumn(format="%+.1f")})
        shown["trail"] = len(trail)


trail_ph = st.empty()
draw_trail(clocks[pos0])
with st.expander("Connectivity monitor log"):
    ml = pd.DataFrame([(t - run["t_end"], ev, f"{a_}-{b_}" if a_ >= 0 else "") for t, ev, a_, b_ in run["monitor_log"]],
                      columns=["t − t_end (s)", "event", "link"])
    st.dataframe(ml, hide_index=True, width="stretch")
st.download_button("Download this run's metrics (CSV)", pd.Series(m).rename("value").to_csv(),
                   file_name=f"run_{sel.dist}_{sel.seed}_{policy}.csv", mime="text/csv")


# ----------------------------------------------------------------------------- playback frames
def render(pos: int) -> None:
    """Frame pos: update the placeholders above; parts that did not change are left alone."""
    clock = clocks[pos]
    PB.show_status(status_ph, pb, where(clock), shown)
    draw_verdict(clock)
    draw_cards(clock)
    draw_censored(clock)
    PB.show_clock(clock_ph, clock, shown, pb, pos, window[1])
    draw_trail(clock)


PB.loop("sim", pb, render)
