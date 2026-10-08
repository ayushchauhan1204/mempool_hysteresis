"""Playback of a finished run on the live pages. Display only.

The run is simulated first (or read from st.cache_data); playback then shows the stored result as it unfolded.

* Time-series charts are drawn once, as the static figure, and never changed during playback. A playback clock t
  (seconds since the disturbance ended) is sent to the page, and each panel is covered to the right of t, so what
  is visible is exactly the stored series up to t (a truncation at t; step traces hold their last value, as a step
  function does). The edge of the cover is the "now" cursor. Nothing is interpolated, smoothed or recomputed, and
  when playback ends the cover is removed: the last frame is the static figure itself. (Streamlit 1.60 redraws a
  Plotly chart from scratch whenever its figure changes, which flickers; covering avoids that.) While playing, one
  marker per run tells the page where the clock starts and how fast it moves, so the cover moves smoothly
  without an update per frame.
* The network graph (one stored snapshot per frame) alternates between two stacked slots, so each redraw happens
  behind the frame on show.
* Metric values, verdicts, table cells and audit-trail rows are hidden ("pending") until the clock passes the
  instant they refer to, then shown with their real value. Values only known at the end of the run (censored
  times, totals) appear in the last frame.
* The loop runs at the end of the page script and only updates placeholders. Any rerun (a widget, the controls,
  a new run) stops it within CHECK_EVERY seconds; the frame reached is kept in st.session_state, so an unrelated
  rerun continues from there and only a new run (or Replay) starts from the beginning. A new run holds its first
  frame until the page reports the chart drawn (Streamlit loads Plotly lazily, which can take seconds on a first
  visit), at most READY_TIMEOUT seconds.
* Static mode (``?static=1`` in the link, or "Show results instantly") renders the final state with no animation.
"""
from __future__ import annotations

import math
import time

N_FRAMES = 48           # frames per playback; the last one is the full, static result
BASE_SECONDS = 4.0      # playback length at 1x
PREROLL = 0.6           # seconds the first frame is held when a playback starts (the page finishes drawing)
READY_TIMEOUT = 4.0     # a new run waits at most this long for the page to report its chart drawn (see loop())
CHECK_EVERY = 0.3       # seconds between the loop's empty updates (how soon a click stops a running playback)
READY_KEY = "mh_pb_ready"
SPEEDS = (0.5, 1.0, 2.0, 4.0)
PENDING = "pending"
CHART_KEY = "pbchart_"  # st.container key prefix of a chart revealed by the playback clock (see app_lib/style.py)
SWAP_KEY = "pbswap_"    # st.container key prefix of the two stacked slots of a redrawn chart


# ------------------------------------------------------------------------------------------- pure helpers
def clocks(t0: float, t1: float, n: int = N_FRAMES) -> list:
    """n playback instants from t0 towards t1. The last entry is None: the full, static result."""
    if n < 2:
        return [None]
    step = (t1 - t0) / (n - 1)
    return [t0 + i * step for i in range(n - 1)] + [None]


def frame_indices(n_items: int, n: int = N_FRAMES) -> list:
    """Increasing, evenly spaced indices into n_items stored snapshots; the first and the last are included."""
    if n_items <= n:
        return list(range(n_items))
    return sorted({round(i * (n_items - 1) / (n - 1)) for i in range(n)})


def revealed(t_event, clock) -> bool:
    """True once the playback clock has passed t_event. None t_event = known only at the end of the run."""
    return clock is None or (t_event is not None and t_event <= clock)


def rows_until(rows, clock) -> list:
    """Rows (time first) up to the clock, e.g. audit-trail entries."""
    return list(rows) if clock is None else [r for r in rows if r[0] <= clock]


def _t(v, censored=False):
    return None if censored or v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def reveal_times(m: dict, dur: float) -> dict:
    """When each value of demo.py's outcome row becomes known, in seconds since the disturbance ended (None: at the
    end of the run). dur = disturbance length (detection is reported after the disturbance started)."""
    det = _t(m["T_det"])
    return {"detected": None if det is None else det - dur,
            "declared": _t(m["T_decl"], m["decl_censored"]),
            "state ok": _t(m["T_conv"], m["conv_censored"]),
            "backlog ok": _t(m["T_bk"], m["bk_censored"]),
            "FRE_state": _t(m["T_conv"], m["conv_censored"]),    # integrated up to T_conv
            "FRE": _t(m["T_true"], m["true_censored"]),          # integrated up to T_true
            "residue@decl": _t(m["T_decl"], m["decl_censored"]),
            "traffic": None}                                     # a total over the whole run


def verdict_time(m: dict):
    """When every event the generated verdict (runs.verdict) refers to has happened; None = end of the run."""
    if (not m["detected"] and m["n_incidents"] == 0) or m["decl_censored"]:
        return None
    decl = float(m["T_decl"])
    if m["FRE_state"] > 0:
        need = (m["T_conv"], m["conv_censored"])
    elif m["FRE"] > 0:
        need = (m["T_bk"], m["bk_censored"])
    else:
        need = (m["T_true"], m["true_censored"])
    t = _t(*need)
    return None if t is None else max(decl, t)


def masked_row(row: dict, times: dict, clock) -> dict:
    """An outcome row with the values not yet known at the clock replaced by PENDING."""
    return {k: (v if revealed(times.get(k), clock) else PENDING) for k, v in row.items()}


def clock_marker(clock: float | None, to: float | None = None, secs: float | None = None,
                 sent_ms: float = 0.0) -> str:
    """The element that carries the playback clock to the page; app_lib/style.py covers the chart beyond it. With
    `to` and `secs` the page moves the clock from `clock` to `to` in `secs` seconds from sent_ms (server time, ms),
    so the cover moves smoothly without one update per frame. clock None: no cover (the static figure)."""
    if clock is None:
        return '<div class="mh-clock" data-done="1"></div>'
    move = "" if secs is None else f' data-to="{to:.6g}" data-secs="{secs:.4g}" data-sent="{sent_ms:.0f}"'
    return f'<div class="mh-clock" data-from="{clock:.6g}"{move}></div>'


# ------------------------------------------------------------------------------------------- state and controls
def _st():
    import streamlit as st
    return st


def static_mode() -> bool:
    """?static=1 in the link: final state at once, no controls (deterministic screenshots)."""
    return str(_st().query_params.get("static", "")).lower() in ("1", "true", "yes")


def prefs() -> dict:
    """Viewer preferences kept for the session, across pages: instant results and speed."""
    return _st().session_state.setdefault("pb_prefs", {"instant": False, "speed": 1.0})


def state(page: str, run_key, n: int) -> dict:
    """Playback state of `page` for the run identified by run_key (n frames). A new run key starts a playback
    (unless static mode or "Show results instantly" is on); any other rerun keeps the current state."""
    pb = _st().session_state.setdefault("pb", {})
    s = pb.get(page)
    if s is None or s["key"] != run_key or s["n"] != n:
        auto = not (static_mode() or prefs()["instant"])
        s = pb[page] = dict(key=run_key, n=n, status="playing" if auto else "done", pos=0 if auto else n - 1,
                            fresh=True, finished=False, ready=False)
    return s


def position(s: dict) -> int:
    return s["pos"] if s["status"] != "done" else s["n"] - 1


def _get(page):
    return _st().session_state["pb"][page]


def _play_pause(page):
    s = _get(page)
    if s["status"] == "playing":
        s["status"] = "paused"
    elif s["status"] == "paused" and s["pos"] < s["n"] - 1:
        s.update(status="playing", ready=True)
    else:
        s.update(status="playing", pos=0, finished=False, ready=True)


def _replay(page):
    _get(page).update(status="playing", pos=0, finished=False, ready=True)


def _skip(page):
    s = _get(page)
    s.update(status="done", pos=s["n"] - 1, finished=True, ready=True)


def _ready():
    """The page script reports the chart drawn: a playback waiting for it starts."""
    for s in _st().session_state.get("pb", {}).values():
        if s["status"] == "playing":
            s["ready"] = True


def _speed(page):
    v = _st().session_state.get(f"pb_speed_{page}")
    if v in SPEEDS:
        prefs()["speed"] = v


def _instant(page):
    on = bool(_st().session_state.get(f"pb_instant_{page}"))
    prefs()["instant"] = on
    if on and _get(page)["status"] != "done":
        _skip(page)


def stop(page: str) -> None:
    """The viewer took over (e.g. moved the time slider): stop the playback where it is, as a finished view."""
    _get(page).update(status="done", finished=False)


def controls(page: str, s: dict):
    """One row of controls (Play/Pause, Replay, Skip to end, speed, instant) and a status line below it.
    Returns the status placeholder, or None in static mode (no controls)."""
    st = _st()
    if static_mode():
        return None
    p = prefs()
    st.session_state.setdefault(f"pb_speed_{page}", p["speed"])
    st.session_state.setdefault(f"pb_instant_{page}", p["instant"])
    playing = s["status"] == "playing"
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"pb_row_{page}"):
        st.button("Pause" if playing else "Play", icon=":material/pause:" if playing else ":material/play_arrow:",
                  key=f"pb_play_{page}", on_click=_play_pause, args=(page,))
        st.button("Replay", icon=":material/replay:", key=f"pb_replay_{page}", on_click=_replay, args=(page,))
        st.button("Skip to end", icon=":material/skip_next:", key=f"pb_skip_{page}", on_click=_skip, args=(page,),
                  disabled=s["status"] == "done")
        st.segmented_control("Speed", SPEEDS, format_func=lambda v: f"{v:g}×", key=f"pb_speed_{page}",
                             required=True, label_visibility="collapsed", on_change=_speed, args=(page,))
        st.toggle("Show results instantly", key=f"pb_instant_{page}", on_change=_instant, args=(page,),
                  help="Skip the playback after each new run (remembered for this session). "
                       "Add ?static=1 to the link for a page without playback controls.")
    st.button(chr(0x200B), key=READY_KEY, type="tertiary", on_click=_ready)   # hidden, blank; the page script clicks it
    return st.empty()


def show_status(ph, s: dict, where: str, memo: dict) -> None:
    """Honest status line: the stored result is being replayed, never recomputed. Sent only when its text changes
    (the playback clock is shown on the chart's cursor)."""
    if ph is None:
        return
    text = {"playing": "Replaying the run from its stored result …",
            "paused": f"Paused at {where}. Play continues, Skip to end shows the full result."}.get(s["status"])
    if memo.get("status", 0) == text:
        return
    memo["status"] = text
    if text:
        ph.caption(text)
    else:
        ph.empty()


def frame_seconds(s: dict) -> float:
    """Wall-clock seconds per frame at the chosen speed."""
    return BASE_SECONDS / max(1, s["n"] - 1) / prefs()["speed"]


def chart_box(name: str):
    """The container of a chart revealed by the playback clock (app_lib/style.py finds it by its key)."""
    return _st().container(key=CHART_KEY + name)


def show_clock(ph, clock, memo: dict, s: dict | None = None, pos: int = 0, end: float | None = None,
               moving: bool = True) -> None:
    """Put the chart's cover at the clock (None: no cover, the full static figure shows). While playing (s given),
    one moving marker per script run carries the clock from frame pos to `end` at the playback pace (moving=False:
    the caller sends the clock every frame). A new run first holds its first frame until the chart is drawn."""
    if clock is not None and s is not None and s["status"] == "playing" and not s.get("ready", True):
        if memo.get("clock") != "waiting":                 # hold the first frame until the chart is drawn
            memo["clock"] = "waiting"
            ph.html(clock_marker(clock).replace("<div ", '<div data-wait="1" ', 1))
        return
    if clock is not None and s is not None and s["status"] == "playing" and moving:
        if memo.get("clock") == "moving":
            return
        memo["clock"] = "moving"
        start = time.time() + (PREROLL if pos == 0 else 0.0)            # loop() holds the first frame as long
        ph.html(clock_marker(clock, end, (s["n"] - 1 - pos) * frame_seconds(s), start * 1000))
        return
    if memo.get("clock", 0) == clock:
        return
    memo["clock"] = clock
    ph.html(clock_marker(clock))


def chart_with_clock(name: str, fig, clock, memo: dict, s: dict | None = None, pos: int = 0,
                     end: float | None = None, box=None, moving: bool = True):
    """Draw a chart revealed by the playback clock and its clock marker; return the marker's placeholder. The chart
    is drawn directly (not into a placeholder), so a rerun keeps it on screen instead of redrawing it, and the
    marker is filled as soon as it is created, so the cover never lapses. box: a container made earlier with
    chart_box(name), to draw into later in the script."""
    st = _st()
    with box if box is not None else chart_box(name):
        st.plotly_chart(fig, width="stretch", theme=None)
        ph = st.empty()
        show_clock(ph, clock, memo, s, pos, end, moving)
    return ph


def swap_slots(name: str):
    """Two stacked placeholders for a chart that is redrawn every frame (see the module docstring)."""
    with _st().container(key=SWAP_KEY + name):
        return _st().empty(), _st().empty()


def loop(page: str, s: dict, render) -> None:
    """Play the remaining frames: render(pos) for each, paced by wall-clock time (frames are dropped, never
    delayed, when rendering falls behind; the last frame is always drawn). Call at the end of the page script.
    Any rerun stops this loop within CHECK_EVERY seconds; the frame reached is kept."""
    if s["status"] != "playing":
        return
    # Streamlit acts on a rerun request (Pause, a new setting, ...) only when the script sends an update, and most
    # frames send none (the cover moves by itself), so an empty update goes out every CHECK_EVERY seconds.
    tick, last = _st().empty(), time.monotonic()
    if not s.get("ready", True):    # a new run: wait for the page to draw the chart (it clicks READY_KEY, a rerun)
        until = last + READY_TIMEOUT
        while time.monotonic() < until:
            time.sleep(CHECK_EVERY)
            tick.empty()
        s["ready"] = True           # no answer (scripts blocked?): play anyway
        _st().rerun()
    n = s["n"]
    dt = frame_seconds(s)
    start = s["pos"]
    t0 = time.monotonic() + (PREROLL if start == 0 else 0.0)
    for pos in range(start + 1, n):
        wait = t0 + (pos - start) * dt - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        elif pos < n - 1 and -wait > dt:
            continue
        render(pos)
        s["pos"] = pos
        if time.monotonic() - last >= CHECK_EVERY:
            tick.empty()
            last = time.monotonic()
    s.update(status="done", finished=True)
    _st().rerun()                                        # redraw the controls for the finished state


def cached_figure(page: str, key, build) -> dict:
    """The static figure as a plain dict, built once per (page, key) and reused across reruns."""
    st = _st()
    store = st.session_state.setdefault("pb_figs", {})
    k = (page, key)
    if k not in store:
        if len(store) > 12:
            store.pop(next(iter(store)))
        store[k] = build().to_dict()
    return store[k]
