"""Colours of the frontend, defined once, with a light and a dark variant.

* Series: the light variant is the paper colour set of demo.py and experiments/figures.py (B1 red, B2 amber,
  SARA blue), unchanged. The dark variant keeps each identity but is stepped for the dark surface: B1 a brighter
  crimson, SARA a lighter blue, B2 the same amber. Checked with the dataviz validator (OKLab, Machado 2009 CVD
  simulation), all pairs: light passes every gate (amber 2.5:1 on the light surface, relieved by the legend and
  the tables); dark passes contrast (>= 4.7:1), CVD separation (10.3) and the normal-vision floor (16.6). The one
  dark miss is the soft lightness band for the amber (L 0.715 > 0.67), kept on purpose: pulling the amber into
  the band drops its CVD separation from the red to 6.0.
* Chrome: ink, muted text, grid and axes per mode (text >= 4.6:1 on its surface in both modes).
* The Streamlit theme itself (backgrounds, text, primary colour, radius) lives in .streamlit/config.toml.
"""
from __future__ import annotations

MODES = ("light", "dark")
DEFAULT_MODE = "dark"                        # matches the default theme the app starts in

SERIES = {
    "light": {"B1": "#c0392b", "B2": "#e08e0b", "SARA": "#1f5fa8", "SARA-D": "#6a9fd4", "SARA-R": "#8e7cc3",
              "SARA-V": "#4aa3a2", "clean": "#7f7f7f"},
    "dark": {"B1": "#e5484d", "B2": "#e08e0b", "SARA": "#4f91e2", "SARA-D": "#7aaee0", "SARA-R": "#a08fd6",
             "SARA-V": "#52b3b1", "clean": "#8f8e88"},
}
CHROME = {
    "light": dict(surface="#fcfcfb", ink="#1b1b1a", ink2="#52514e", muted="#75736d", grid="#e9e8e2",
                  axis="#c3c2b7", cursor="#1b1b1a", dist_shade="#f5c6c0", dist_opacity=0.45,
                  hl_bg="rgba(192, 57, 43, 0.14)"),
    "dark": dict(surface="#141413", ink="#ecebe6", ink2="#c3c2b7", muted="#8f8d86", grid="#262624",
                 axis="#5f5d57", cursor="#ecebe6", dist_shade="#e5484d", dist_opacity=0.14,
                 hl_bg="rgba(229, 72, 77, 0.20)"),
}
STATUS = {    # status palette (link states), never used for a series
    "light": {"critical": "#d03b3b", "serious": "#ec835a", "muted": "#a7a59c"},
    "dark": {"critical": "#e5484d", "serious": "#ec835a", "muted": "#8f8d86"},
}
NODE_SCALE = {    # share of the pending set a node holds: more = more contrast against the surface
    "light": [[0.0, "#f4f3ef"], [0.5, "#a7a59c"], [1.0, "#2b2a28"]],
    "dark": [[0.0, "#2c2c29"], [0.5, "#75736c"], [1.0, "#e6e4dc"]],
}
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"


def norm(mode: str | None) -> str:
    return mode if mode in MODES else DEFAULT_MODE


def current_mode() -> str:
    """Theme type of the running app ("light" or "dark"); the default mode outside Streamlit or before the
    browser has reported it."""
    try:
        import streamlit as st
        return norm(st.context.theme.type)
    except Exception:                       # no script run context (tests, bare python)
        return DEFAULT_MODE


def series(mode: str | None = None) -> dict:
    return SERIES[norm(mode) if mode else current_mode()]


def chrome(mode: str | None = None) -> dict:
    return CHROME[norm(mode) if mode else current_mode()]
