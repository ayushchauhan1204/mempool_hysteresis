"""Plotly figure builders for the frontend.

Policy colours match demo.py and experiments/figures.py (B1 red, B2 amber, SARA blue) in the light theme, with
brighter steps of the same identities in the dark theme (app_lib/palette.py). Each builder takes ``mode`` ("light" or
"dark"; default: the running app's theme). Measures with different units are drawn as stacked panels sharing the
time axis, never on two y-scales of one panel. Time is seconds relative to the end of the disturbance, as in demo.py.
"""
from __future__ import annotations

import math

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import palette as C
from . import runs as R

FONT = C.FONT
TIERS = ("LOW", "MODERATE", "HIGH", "CRITICAL")


def pcol(mode: str | None = None) -> dict:
    """Policy colours for the theme (default: the running app's)."""
    return C.series(mode)


def _mode(mode):
    return C.norm(mode) if mode else C.current_mode()


def _edge_style(mode):
    """True link state: colour (status palette) + dash, so state is never colour alone."""
    s, c = C.STATUS[mode], C.CHROME[mode]
    return {"healthy": dict(color=c["axis"], width=1.4, dash="solid"),
            "cut": dict(color=s["critical"], width=2.6, dash="dash"),
            "reconnecting": dict(color=s["muted"], width=2.0, dash="dot"),
            "blackholed": dict(color=s["critical"], width=2.6, dash="dot"),
            "degraded": dict(color=s["serious"], width=3.0, dash="solid")}


def template(mode: str) -> go.layout.Template:
    """Plotly template of the theme: only the layout defaults these charts use. The stock plotly_white/plotly_dark
    templates carry defaults for every trace type and make each playback frame about a third slower to draw."""
    c = C.CHROME[mode]
    axis = dict(gridcolor=c["grid"], linecolor=c["axis"], tickcolor=c["axis"], zerolinecolor=c["axis"], automargin=True,
                title=dict(font=dict(color=c["ink2"])), tickfont=dict(color=c["ink2"]))
    return go.layout.Template(layout=dict(
        font=dict(family=FONT, color=c["ink2"]), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=list(C.SERIES[mode].values()), xaxis=axis, yaxis=axis,
        hoverlabel=dict(bgcolor=c["surface"], bordercolor=c["axis"], font=dict(family=FONT, color=c["ink"])),
        legend=dict(font=dict(color=c["ink2"])), annotationdefaults=dict(font=dict(color=c["ink2"])),
        updatemenudefaults=dict(bgcolor=c["surface"], bordercolor=c["axis"], font=dict(color=c["ink2"])),
        sliderdefaults=dict(bgcolor=c["grid"], bordercolor=c["axis"], activebgcolor=c["axis"], tickcolor=c["axis"],
                            font=dict(color=c["ink2"]))))


def _style(fig, height, mode):
    c = C.CHROME[mode]
    fig.update_layout(template=template(mode), height=height,
                      margin=dict(l=70, r=20, t=40, b=40), font=dict(family=FONT, size=13, color=c["ink2"]),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                                                         bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(gridcolor=c["grid"], linecolor=c["axis"], zeroline=False, ticks="outside", tickcolor=c["axis"],
                     showspikes=True, spikemode="across", spikethickness=1, spikecolor=c["muted"], spikedash="solid")
    fig.update_yaxes(gridcolor=c["grid"], linecolor=c["axis"], zeroline=False, rangemode="tozero")
    return fig


def x_range(run):
    """Visible time window (seconds since the disturbance ended); playback runs over the same window."""
    dur = run["t_end"] - run["dist_start"]
    return [-dur - 30, min(480.0, run["horizon"] - run["t_end"])]


def _disturbance(fig, run, rows, mode):
    dur = run["t_end"] - run["dist_start"]
    c = C.CHROME[mode]
    for r in rows:
        fig.add_vrect(x0=-dur, x1=0, fillcolor=c["dist_shade"], opacity=c["dist_opacity"], line_width=0,
                      layer="below", row=r, col=1)


def _status_xy(timeline, te, horizon):
    xs, ys = [], []
    for t, s in timeline:
        xs.append(t - te)
        ys.append(1 if s == "incident" else 0)
    xs.append(horizon - te)
    ys.append(ys[-1])
    return xs, ys


def _vline(fig, x, color, rows, dash="dot", width=1.4):
    """An event line (declaration, convergence): shown in playback once the clock reaches x."""
    for r in rows:
        fig.add_vline(x=x, line_color=color, line_dash=dash, line_width=width, row=r, col=1)


def _empty_note(fig, series_list, row, text, mode):
    """Say so when a truth panel is empty (e.g. packet loss leaves no residue). Call after styling titles.
    A statement about the whole run, so playback shows it in the last frame only."""
    if not any(np.any(np.nan_to_num(np.asarray(v, float)) > 0) for v in series_list):
        fig.add_annotation(text=text, xref="paper", yref="y domain" if row == 1 else f"y{row} domain", x=0.5, y=0.5,
                           showarrow=False, font=dict(size=13, color=C.CHROME[mode]["muted"]))


# ------------------------------------------------------------------------------------------- one run
def run_figure(run: dict, mode: str | None = None) -> go.Figure:
    """Truth (residue, excess backlog, evicted-divergence if capped) above what the policy reported and watched."""
    mode = _mode(mode)
    c = C.CHROME[mode]
    p = run["policy"]
    pc = C.SERIES[mode]
    col = pc.get(p, pc["SARA"])
    te = run["t_end"]
    s = run["series"]
    capped = run["mempool_cap"] is not None
    titles = ["True state: residue (tx)", "True state: excess backlog vs the clean history (tx)"]
    if capped:
        titles.append("True state: evicted-divergence (tx)")
    titles += [f"What {p} reported", "What it watched: " + ("SARA risk tier" if p.startswith("SARA")
                                                           else "links the connectivity monitor flags unhealthy")]
    n = len(titles)
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.06, subplot_titles=titles,
                        row_heights=[1.2, 1.0] + ([1.0] if capped else []) + [0.55, 0.75])
    t = s["t"] - te
    fig.add_trace(go.Scatter(x=t, y=s["residue"], mode="lines", line=dict(color=col, width=2), name="residue",
                             hovertemplate="%{y:.0f} tx"), row=1, col=1)
    fig.add_trace(go.Scatter(x=t, y=R.excess_backlog(run), mode="lines", line=dict(color=col, width=2),
                             name="excess backlog", hovertemplate="%{y:.0f} tx"), row=2, col=1)
    r = 3
    if capped:
        fig.add_trace(go.Scatter(x=t, y=s["evdiv"], mode="lines", line=dict(color=col, width=2),
                                 name="evicted-divergence", hovertemplate="%{y:.0f} tx"), row=r, col=1)
        r += 1
    xs, ys = _status_xy(run["timeline"], te, run["horizon"])
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=col, width=2, shape="hv"), fill="tozeroy",
                             fillcolor="rgba(128,128,128,0.08)", name="reported status",
                             hovertemplate="%{customdata}", customdata=["incident" if v else "recovered" for v in ys]),
                  row=r, col=1)
    fig.update_yaxes(tickvals=[0, 1], ticktext=["recovered", "incident"], range=[-0.15, 1.25], row=r, col=1)
    r += 1
    if run["audit_log"] is not None and len(run["audit_log"]):
        a = run["audit_log"]
        fig.add_trace(go.Scatter(x=a[:, 0] - te, y=a[:, 4], mode="lines", line=dict(color=col, width=2, shape="hv"),
                                 name="risk tier", customdata=[TIERS[int(v)] for v in a[:, 4]],
                                 hovertemplate="%{customdata}"), row=r, col=1)
        fig.update_yaxes(tickvals=[0, 1, 2, 3], ticktext=list(TIERS), range=[-0.3, 3.3], row=r, col=1)
    else:
        steps = R.monitor_unhealthy_steps(run["monitor_log"]) + [(run["horizon"], None)]
        xs = [x - te for x, _ in steps]
        ys = [y for _, y in steps[:-1]] + [steps[-2][1]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=col, width=2, shape="hv"),
                                 name="unhealthy links", hovertemplate="%{y:.0f} links"), row=r, col=1)
    _disturbance(fig, run, range(1, n + 1), mode)
    m = run["metrics"]
    if not m["decl_censored"]:
        _vline(fig, m["T_decl"], col, range(1, n + 1))
    if not m["conv_censored"]:
        _vline(fig, m["T_conv"], c["ink2"], range(1, n + 1), dash="solid", width=1)
    fig.update_xaxes(range=x_range(run))
    fig.update_xaxes(title_text="seconds since the disturbance ended   (dotted: recovery declared; "
                                "solid grey: residue cleared and stayed clear)", row=n, col=1)
    _style(fig, 150 * n + 110, mode)
    fig.update_layout(showlegend=False)
    fig.update_annotations(font=dict(size=13, color=c["ink2"]), x=0, xanchor="left")
    _empty_note(fig, [s["residue"]], 1, "no residue in this run", mode)
    if capped:
        _empty_note(fig, [s["evdiv"]], 3, "no evicted-divergence in this run", mode)
    return fig


# ------------------------------------------------------------------------------------------- comparison
def compare_figure(runs: dict, mode: str | None = None) -> go.Figure:
    """Residue, excess backlog (and evicted-divergence) per policy, plus each policy's reported status."""
    mode = _mode(mode)
    c = C.CHROME[mode]
    any_run = next(iter(runs.values()))
    te = any_run["t_end"]
    capped = any_run["mempool_cap"] is not None
    titles = ["True state: residue (tx)", "True state: excess backlog vs the clean history (tx)"]
    if capped:
        titles.append("True state: evicted-divergence (tx)")
    titles.append("What each policy reported (bar = incident open; thin line = 'recovered')")
    n = len(titles)
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.07, subplot_titles=titles,
                        row_heights=[1.2, 1.0] + ([1.0] if capped else []) + [0.7])
    pc = C.SERIES[mode]
    for i, (p, run) in enumerate(runs.items()):
        col = pc[p]
        t = run["series"]["t"] - te
        fig.add_trace(go.Scatter(x=t, y=run["series"]["residue"], mode="lines", line=dict(color=col, width=2),
                                 name=p, legendgroup=p, hovertemplate=f"{p}: " + "%{y:.0f} tx<extra></extra>"),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=t, y=R.excess_backlog(run), mode="lines", line=dict(color=col, width=2),
                                 name=p, legendgroup=p, showlegend=False,
                                 hovertemplate=f"{p}: " + "%{y:.0f} tx<extra></extra>"), row=2, col=1)
        if capped:
            fig.add_trace(go.Scatter(x=t, y=run["series"]["evdiv"], mode="lines", line=dict(color=col, width=2),
                                     name=p, legendgroup=p, showlegend=False,
                                     hovertemplate=f"{p}: " + "%{y:.0f} tx<extra></extra>"), row=3, col=1)
        # swimlane: incident intervals thick, recovered intervals thin
        tl = run["timeline"] + [(run["horizon"], run["timeline"][-1][1])]
        for (a, sa), (b, _) in zip(tl[:-1], tl[1:]):
            if b <= a:
                continue
            fig.add_trace(go.Scatter(x=[a - te, b - te], y=[p, p], mode="lines", showlegend=False, legendgroup=p,
                                     line=dict(color=col, width=14 if sa == "incident" else 2),
                                     hovertemplate=f"{p}: {sa} {a - te:+.0f} s to {b - te:+.0f} s<extra></extra>"),
                          row=n, col=1)
        m = run["metrics"]
        if not m["decl_censored"]:
            _vline(fig, m["T_decl"], col, range(1, n))
    fig.update_yaxes(categoryorder="array", categoryarray=list(runs)[::-1], row=n, col=1)
    _disturbance(fig, any_run, range(1, n + 1), mode)
    fig.update_xaxes(range=x_range(any_run))
    fig.update_xaxes(title_text="seconds since the disturbance ended   (dotted: when each policy declared recovery)",
                     row=n, col=1)
    _style(fig, 170 * n + 120, mode)
    fig.update_layout(legend=dict(x=1, xanchor="right", y=1.04, yanchor="bottom"))
    fig.update_annotations(font=dict(size=13, color=c["ink2"]), x=0, xanchor="left")
    _empty_note(fig, [r["series"]["residue"] for r in runs.values()], 1, "no residue under any policy", mode)
    if capped:
        _empty_note(fig, [r["series"]["evdiv"] for r in runs.values()], 3, "no evicted-divergence under any policy",
                    mode)
    return fig


# ------------------------------------------------------------------------------------------- Extension A
def delay_figure(runs: dict, bin_s: float = 10.0, mode: str | None = None) -> go.Figure:
    """Mean confirmation delay of shared-workload transactions by creation time (10 s bins), each run against
    the paired clean history. Transactions never confirmed by the end of the run are left out of the means."""
    mode = _mode(mode)
    pc, c = C.SERIES[mode], C.CHROME[mode]
    any_run = next(iter(runs.values()))
    te = any_run["t_end"]
    fig = go.Figure()
    pt = any_run["ext_a"]["per_tx"]
    rel = np.asarray(pt["created"]) - te
    edges = np.arange(math.floor(rel.min() / bin_s) * bin_s, rel.max() + bin_s, bin_s)
    mid = (edges[:-1] + edges[1:]) / 2

    def binned(delay):
        out = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (rel >= lo) & (rel < hi) & np.isfinite(delay)
            out.append(float(np.mean(delay[m])) if m.any() else None)
        return out
    fig.add_trace(go.Scatter(x=mid, y=binned(np.asarray(pt["clean_delay"])), mode="lines",
                             line=dict(color=pc["clean"], width=2, dash="dash"), name="clean history",
                             hovertemplate="clean: %{y:.1f} s<extra></extra>"))
    for p, run in runs.items():
        d = np.asarray(run["ext_a"]["per_tx"]["delay"])
        fig.add_trace(go.Scatter(x=mid, y=binned(d), mode="lines", line=dict(color=pc.get(p, pc["SARA"]), width=2),
                                 name=p, hovertemplate=f"{p}: " + "%{y:.1f} s<extra></extra>"))
    dur = te - any_run["dist_start"]
    fig.add_vrect(x0=-dur, x1=0, fillcolor=c["dist_shade"], opacity=c["dist_opacity"], line_width=0, layer="below")
    fig.update_xaxes(title_text="creation time, seconds since the disturbance ended (10 s bins)")
    fig.update_yaxes(title_text="mean confirmation delay (s)")
    _style(fig, 340, mode)
    return fig


# ------------------------------------------------------------------------------------------- replay
def network_figure(rp: dict, k: int, mode: str | None = None) -> go.Figure:
    """Node graph at frame k: node shade = share of the network-wide pending set the node holds; edge style = true
    link state; x = link the connectivity monitor currently flags unhealthy; ring = node targeted by the
    disturbance."""
    mode = _mode(mode)
    c = C.CHROME[mode]
    f = rp["frames"][k]
    pos = rp["positions"]
    states = rp["link_states"][k]
    fig = go.Figure()
    for state, sty in _edge_style(mode).items():
        xs, ys = [], []
        for (a, b), st_ in zip(rp["edges"], states):
            if st_ == state:
                xs += [pos[a][0], pos[b][0], None]
                ys += [pos[a][1], pos[b][1], None]
        fig.add_trace(go.Scatter(x=xs or [None], y=ys or [None], mode="lines", line=sty, hoverinfo="skip",
                                 name=f"link {state}", showlegend=True))
    bad = f["monitor_unhealthy"]
    fig.add_trace(go.Scatter(x=[(pos[a][0] + pos[b][0]) / 2 for a, b in bad] or [None],
                             y=[(pos[a][1] + pos[b][1]) / 2 for a, b in bad] or [None], mode="markers",
                             marker=dict(symbol="x", size=9, color=c["ink2"]), name="monitor: link unhealthy",
                             hoverinfo="skip"))
    n = rp["n"]
    capped = "evicted" in f
    hover = []
    for i in range(n):
        h = (f"node {i}<br>pending {f['pending'][i]} ({f['share'][i]:.0%} of all pending)<br>tip height "
             f"{f['heights'][i]}")
        if f["residue"] is not None:
            h += f"<br>residue tx it lacks: {f['lacks'][i]}<br>residue tx it holds: {f['holds'][i]}"
        if capped:
            h += (f"<br>evicted so far: {f['evicted'][i]}<br>rejected so far: {f['rejected'][i]}"
                  f"<br>minimum fee: {f['min_fee'][i]:.2f}")
        hover.append(h)
    affected = set(rp["affected"])
    size = 30 if n <= 12 else 22 if n <= 25 else 14
    # node labels: dark ink on light fills, light ink on dark fills (the scale runs the other way in dark mode)
    light_fill = (lambda s: s <= 0.78) if mode == "light" else (lambda s: s > 0.78)
    ink_on = {True: C.CHROME["light"]["ink"], False: C.CHROME["dark"]["ink"]}
    fig.add_trace(go.Scatter(
        x=[pos[i][0] for i in range(n)], y=[pos[i][1] for i in range(n)], mode="markers+text",
        text=[str(i) for i in range(n)] if n <= 25 else None, textposition="middle center",
        textfont=dict(color=[ink_on[light_fill(s)] for s in f["share"]], size=11),
        # fixed 50-100% scale (the same in every frame): healthy nodes hold nearly everything, so the interesting
        # differences lie in the upper half; anything at or below 50% gets the faintest shade
        marker=dict(size=size, color=f["share"], cmin=0.5, cmax=1.0, colorscale=C.NODE_SCALE[mode],
                    line=dict(width=[3 if i in affected else 1 for i in range(n)],
                              color=[c["ink"] if i in affected else c["axis"] for i in range(n)]),
                    colorbar=dict(title=dict(text="share of all pending tx held", side="right"), thickness=12,
                                  len=0.8, tickvals=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0], outlinewidth=0,
                                  ticktext=["≤50%", "60%", "70%", "80%", "90%", "100%"])),
        hovertext=hover, hoverinfo="text", name="nodes", showlegend=False))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(template=template(mode), height=520,
                      margin=dict(l=10, r=10, t=10, b=10), font=dict(family=FONT, size=12, color=c["ink2"]),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="top", y=-0.02, x=0, font=dict(size=11)),
                      hovermode="closest", meta=f"frame {k}")   # distinct per frame (two playback slots)
    return fig


def replay_strip(rp: dict, k: int | None, mode: str | None = None) -> go.Figure:
    """Evaluator residue over time for this run (and evicted-divergence with a cap), frame k marked (k None: no
    mark; the Network replay page adds it per frame with playback.frame_figure)."""
    mode = _mode(mode)
    c = C.CHROME[mode]
    te = rp["t_end"]
    s = rp["residue_series"]
    pc = C.SERIES[mode]
    col = pc.get(rp["policy"], pc["SARA"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s["t"] - te, y=s["residue"], mode="lines", line=dict(color=col, width=2),
                             name="residue", hovertemplate="residue %{y:.0f} tx<extra></extra>"))
    if "evdiv" in s:
        fig.add_trace(go.Scatter(x=s["t"] - te, y=s["evdiv"], mode="lines", line=dict(color=col, width=1.5, dash="dot"),
                                 name="evicted-divergence", hovertemplate="evicted-div. %{y:.0f} tx<extra></extra>"))
    dur = te - rp["dist_start"]
    fig.add_vrect(x0=-dur, x1=0, fillcolor=c["dist_shade"], opacity=c["dist_opacity"], line_width=0, layer="below")
    if k is not None:
        fig.add_vline(x=rp["frames"][k]["t"] - te, line_color=c["cursor"], line_width=1.5)
    fig.update_xaxes(title_text="seconds since the disturbance ended", range=[s["t"][0] - te, s["t"][-1] - te])
    fig.update_yaxes(title_text="tx")
    _style(fig, 220, mode)
    fig.update_layout(margin=dict(l=60, r=20, t=30, b=40), showlegend="evdiv" in s)
    return fig


def animated_network(rp: dict, step: int = 1, mode: str | None = None) -> go.Figure:
    """The same node graph as network_figure, animated in the browser (play / pause and a frame slider)."""
    mode = _mode(mode)
    ks = list(range(0, len(rp["frames"]), step))
    base = network_figure(rp, ks[0], mode)
    frames = []
    for k in ks:
        fk = network_figure(rp, k, mode)
        frames.append(go.Frame(data=fk.data, name=str(k)))
    base.frames = frames
    te = rp["t_end"]
    steps = [dict(method="animate", label=f"{rp['frames'][k]['t'] - te:+.0f}",
                  args=[[str(k)], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
             for k in ks]
    base.update_layout(
        height=600,
        updatemenus=[dict(type="buttons", showactive=False, x=0, y=1.08, xanchor="left", direction="left",
                          buttons=[dict(label="Play", method="animate",
                                        args=[None, dict(frame=dict(duration=350, redraw=True), fromcurrent=True,
                                                         transition=dict(duration=0))]),
                                   dict(label="Pause", method="animate",
                                        args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False))])])],
        sliders=[dict(active=0, steps=steps, x=0.12, len=0.88, y=1.06, yanchor="bottom",
                      currentvalue=dict(prefix="t − t_end = ", suffix=" s"))])
    return base


# ------------------------------------------------------------------------------------------- study results
def sweep_figure(long_df, xlabel: str, mode: str | None = None) -> go.Figure:
    """Main-study robustness sweep: per-seed means with stored 95% CIs, one panel per metric (values as stored)."""
    mode = _mode(mode)
    pc = C.SERIES[mode]
    metrics = [("T_conv", "time to state convergence (s)"), ("FRE_state", "FRE, state component (s)"),
               ("FRE", "FRE overall (s)")]
    fig = make_subplots(rows=1, cols=3, subplot_titles=[m[1] for m in metrics], horizontal_spacing=0.08)
    for c, (metric, _) in enumerate(metrics, start=1):
        for p in ("B1", "B2", "SARA"):
            d = long_df[(long_df.metric == metric) & (long_df.policy == p)]
            fig.add_trace(go.Scatter(x=d.x, y=d["mean"], mode="lines+markers", line=dict(color=pc[p], width=2),
                                     marker=dict(size=8), name=p, legendgroup=p, showlegend=c == 1,
                                     error_y=dict(type="data", symmetric=False, array=d.ci_hi - d["mean"],
                                                  arrayminus=d["mean"] - d.ci_lo, color=pc[p], thickness=1, width=4),
                                     hovertemplate=f"{p}: " + "%{y:.1f}<extra></extra>"), row=1, col=c)
        fig.update_xaxes(title_text=xlabel, type="category", row=1, col=c)
    _style(fig, 360, mode)
    fig.update_layout(hovermode="closest")
    fig.update_annotations(font=dict(size=13, color=C.CHROME[mode]["ink2"]))
    return fig
