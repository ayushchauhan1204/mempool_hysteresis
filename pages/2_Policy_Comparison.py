"""Policy comparison: B1 vs B2 vs SARA on the same seed and disturbance (what demo.py prints, live).

After a new run the result plays back (app_lib/playback.py): the residue curves draw in over time, and the
believed-vs-true table, the verdicts and the audit trails fill in per policy as it declares and converges. Display
only; the last frame is the static result."""
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
POLS = R.COMPARE_POLICIES
st.title("Policy comparison")
st.caption("The same seed and disturbance under B1, B2 and SARA. Common random numbers: every policy sees the same "
           "workload, mining schedule and network luck, so differences come from the policies.")
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


def run_all(dist, overrides, bar, start, total):
    out = {}
    R.reference_run(sel.seed, R.make_config(overrides).t_end(dist), overrides)
    bar.progress((start + 1) / total, text=f"{R.DIST_LABEL[dist]}: clean reference history")
    for k, p in enumerate(POLS):
        out[p] = R.policy_run(sel.seed, dist, p, overrides)
        bar.progress((start + 2 + k) / total, text=f"{R.DIST_LABEL[dist]}: {p}")
    return out


bar = st.progress(0.0, text="Running the clean reference and three policies …")
try:
    runs = run_all(sel.dist, ov, bar, 0, 1 + len(POLS))
except Exception as e:
    st.error(f"The runs failed: {e}")
    st.stop()
bar.empty()
any_run = runs["B1"]
theme = C.current_mode()
pcol = C.SERIES[theme]
run_key = (sel.seed, sel.dist, ov, ui.applied())
window = P.x_range(any_run)
clocks = PB.clocks(*window)
pb = PB.state("cmp", run_key, len(clocks))
pos0 = PB.position(pb)
shown = {}                                   # what each placeholder shows now (only changes are sent)


def where(clock):
    return "the end of the run" if clock is None else f"{clock:+.0f} s"


status_ph = PB.controls("cmp", pb)
PB.show_status(status_ph, pb, where(clocks[pos0]), shown)
st.code(any_run["describe"], language=None)

st.subheader("Believed vs true")
outcome = {p: R.outcome_row(runs[p]["metrics"]) for p in POLS}
dur = any_run["t_end"] - any_run["dist_start"]
reveal = {p: PB.reveal_times(runs[p]["metrics"], dur) for p in POLS}


def _hl(col):
    return [f"background-color: {C.CHROME[theme]['hl_bg']}; font-weight: 600" if col.name == "FRE_state" else ""
            for _ in col]


def draw_table(clock):
    values = {p: PB.masked_row(outcome[p], reveal[p], clock) for p in POLS}
    if shown.get("table") != values:
        table = pd.DataFrame(values).T
        table.index.name = "policy"
        table_ph.dataframe(table.style.apply(_hl), width="stretch")
        shown["table"] = values


table_ph = st.empty()
draw_table(clocks[pos0])
st.caption("Exactly the table `python demo.py` prints. detected = after the disturbance started; declared / state ok / "
           "backlog ok = after it ended. FRE = seconds the policy reported 'recovered' while the true state had not "
           "recovered (FRE_state: residue remained).")


def draw_verdicts(clock):
    for p in POLS:
        m = runs[p]["metrics"]
        verdict = R.verdict(m) if PB.revealed(PB.verdict_time(m), clock) else None
        if shown.get(("verdict", p), 0) != verdict:
            verdict_ph[p].markdown(f"<span style='color:{pcol[p]};font-weight:700'>{p}</span> — "
                                   + (verdict or ":gray[Pending until the events it describes have happened.]"),
                                   unsafe_allow_html=True)
            shown[("verdict", p)] = verdict


verdict_ph = {p: st.empty() for p in POLS}
draw_verdicts(clocks[pos0])

st.subheader("What was true, and what each policy reported")
clock_ph = PB.chart_with_clock("cmp", PB.cached_figure("cmp", (run_key, theme), lambda: P.compare_figure(runs, theme)),
                               clocks[pos0], shown, pb, pos0, window[1])

st.subheader("Effect on users (extension A metrics)")
rows = []
for p in POLS:
    a = runs[p]["ext_a"]
    rows.append({"policy": p, "excess delay, all exposed tx (s)": a["exposed"]["excess"]["mean"],
                 "created during (s)": a["during"]["excess"]["mean"], "created after (s)": a["after"]["excess"]["mean"],
                 "confirmed in clean only": a["exposed"]["excess"]["never_extra"],
                 "block-composition distance": a["blocks"]["bcd"]})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
    c: st.column_config.NumberColumn(format="%.2f") for c in ("excess delay, all exposed tx (s)", "created during (s)",
                                                               "created after (s)")} | {
    "block-composition distance": st.column_config.NumberColumn(format="%.3f")})
st.caption("Mean per-transaction excess confirmation delay against the paired clean history (shared workload; "
           "unconfirmed censored at the end of the run, so a lower bound). Windows: 120 s before, during, and 300 s "
           "after the disturbance.")
st.plotly_chart(P.delay_figure(runs, mode=theme), width="stretch", theme=None)

if any_run["mempool_cap"] is not None:
    st.subheader(f"Bounded mempools: {any_run['mempool_cap']} transactions per node (extension C metrics)")
    rows = []
    for p in POLS:
        c = runs[p]["ext_c"]
        rows.append({"policy": p, "evicted": c["evicted"], "rejected": c["rejected"],
                     "evicted-divergence +10 s": c["evdiv_10"], "+300 s": c["evdiv_300"], "lost at the end": c["lost_end"],
                     "unrepairable gaps (SARA)": c["unrepairable"] if p.startswith("SARA") else None,
                     "declared before the end": not runs[p]["metrics"]["decl_censored"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

st.subheader("Audit trails")
cols = st.columns(len(POLS))
trail_ph, trail_all = {}, {}
for c, p in zip(cols, POLS):
    c.markdown(f"<span style='color:{pcol[p]};font-weight:700'>{R.POLICY_LABEL[p]}</span>", unsafe_allow_html=True)
    trail_all[p] = R.audit_trail(runs[p])
    trail_ph[p] = c.empty()


def draw_trails(clock):
    for p in POLS:
        trail = PB.rows_until(trail_all[p], clock)
        if shown.get(("trail", p)) != len(trail):
            trail_ph[p].dataframe(pd.DataFrame(trail, columns=["t − t_end (s)", "entry"]), hide_index=True,
                                  width="stretch", height=360,
                                  column_config={"t − t_end (s)": st.column_config.NumberColumn(format="%+.1f")})
            shown[("trail", p)] = len(trail)


draw_trails(clocks[pos0])

st.subheader("All six disturbances for this seed")
st.caption("The equivalent of `python demo.py --dist all`: FRE_state per disturbance and policy (24 runs, cached).")
key = ("grid", sel.seed, sel.raw_overrides)
if st.button("Run all six disturbances"):
    st.session_state["grid_key"] = key
if st.session_state.get("grid_key") == key:
    total = len(R.DISTURBANCES) * (1 + len(POLS))
    bar = st.progress(0.0, text="Running …")
    grid = {}
    for i, d in enumerate(R.DISTURBANCES):
        rs = run_all(d, sel.overrides(d), bar, i * (1 + len(POLS)), total)
        grid[R.DIST_LABEL[d]] = {f"{p} FRE_state": R.fmt(rs[p]["metrics"]["FRE_state"]) for p in POLS}
    bar.empty()
    st.dataframe(pd.DataFrame(grid).T, width="stretch")


# ----------------------------------------------------------------------------- playback frames
def render(pos: int) -> None:
    """Frame pos: update the placeholders above; parts that did not change are left alone."""
    clock = clocks[pos]
    PB.show_status(status_ph, pb, where(clock), shown)
    draw_table(clock)
    draw_verdicts(clock)
    PB.show_clock(clock_ph, clock, shown, pb, pos, window[1])
    draw_trails(clock)


PB.loop("cmp", pb, render)
