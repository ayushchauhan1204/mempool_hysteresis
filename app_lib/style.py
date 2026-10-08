"""Look of the app: one CSS block for rounded corners, plus a small page script (theme helper and the playback
cover). Call ``apply()`` once per page.

* Palette and base radius come from .streamlit/config.toml ([theme], [theme.light], [theme.dark]). The CSS here only
  rounds and frames what the config does not reach (metric cards, chart containers, images) with one radius,
  and uses currentColor-derived borders and fills, so it works unchanged in both themes.
* Dark is the default theme. Streamlit 1.60 starts in "System" when both a light and a dark theme are configured,
  so the script stores "Dark" as the theme choice once, on a first visit, and reloads. A choice made later in the
  Settings menu (System / Light / Dark) is remembered and also applied to pages opened directly by link.
* Charts are drawn for the theme the browser reports with each rerun (st.context.theme). Switching the theme in the
  Settings menu does not rerun the script in 1.60, so the script asks for one rerun (through a hidden button)
  whenever the page's theme differs from the one the charts were drawn for. A rerun never restarts a playback.
* Playback (app_lib/playback.py): the script covers a chart beyond the playback clock and moves the cover; see the
  comment in the script.
* If the browser blocks storage or scripts, nothing breaks: the app follows the system theme, charts update on the
  next interaction, and playback shows the full charts (cards, verdicts and tables still play back).
"""
from __future__ import annotations

import streamlit as st

from . import palette

RADIUS = "14px"     # one corner radius for every surface (config.toml baseRadius uses the same value)
SYNC_KEY = "mh_theme_sync"

CSS = f"""
<style>
[data-testid="stMetric"] {{
  padding: 12px 16px; border-radius: {RADIUS};
  border: 1px solid rgba(128, 128, 128, 0.22); border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  background: rgba(128, 128, 128, 0.05); background: color-mix(in srgb, currentColor 4%, transparent);
  box-shadow: 0 1px 2px rgba(20, 20, 19, 0.06);
}}
[data-testid="stPlotlyChart"] {{
  border-radius: {RADIUS}; overflow: hidden; padding: 6px 4px 2px;
  border: 1px solid rgba(128, 128, 128, 0.18); border: 1px solid color-mix(in srgb, currentColor 10%, transparent);
}}
[data-testid="stExpander"] details, [data-testid="stAlert"] > div, [data-testid="stDataFrame"],
[data-testid="stTable"], [data-testid="stCode"] pre, [data-testid="stImage"] img,
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: {RADIUS}; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ overflow: hidden; }}
.st-key-{SYNC_KEY}, .st-key-mh_pb_ready, .stElementContainer:has(#mh-theme-sync), .stElementContainer:has(.mh-clock) {{
  display: none !important; }}
[class*="st-key-pbswap_"] {{ display: grid !important; grid-template-columns: minmax(0, 1fr); }}
[class*="st-key-pbswap_"] > * {{ grid-area: 1 / 1; width: 100%; min-width: 0; }}
</style>
"""

_SCRIPT = """
<div id="mh-theme-sync" data-mode="{mode}"></div>
<script>
(function () {{
  const KEY = (p) => "stActiveTheme-" + p + "-v2";      // where Streamlit 1.60 keeps the Settings-menu choice
  let ls = null;
  try {{ ls = window.localStorage; }} catch (e) {{}}
  if (!window.__mhTheme) {{
    window.__mhTheme = {{ path: location.pathname, asked: null, adopted: false }};
    if (ls) {{
      try {{
        // Streamlit stores "System" for a path on its first load, so a path this app has not seen yet gets the
        // default (Dark) or the last choice made on another page, once.
        const here = KEY(location.pathname);
        const seen = JSON.parse(ls.getItem("mh-theme-paths") || "[]");
        if (!seen.includes(location.pathname)) {{
          const pref = ls.getItem("mh-theme") || '"Dark"';
          seen.push(location.pathname);
          ls.setItem("mh-theme-paths", JSON.stringify(seen));
          if (ls.getItem(here) !== pref && JSON.parse(ls.getItem("mh-theme-paths")).includes(location.pathname)) {{
            ls.setItem(here, pref);
            if (ls.getItem(here) === pref) {{ location.reload(); return; }}
          }}
        }}
        window.__mhTheme.adopted = true;
      }} catch (e) {{}}
    }}
    // Playback (app_lib/playback.py): cover each panel of a chart to the right of the playback clock, so the stored
    // series shows up to the clock only. The cover's left edge is the "now" cursor. No marker: no cover. A marker
    // with data-secs moves the clock from data-from to data-to in that many seconds (counted from data-sent, the
    // server's send time, so the cover keeps pace with the cards); without data-secs the clock stands at data-from.
    const label = (c) => (c >= 0.5 ? "+" : "") + Math.round(c) + " s";
    function covers(now) {{
      try {{
        const app = document.querySelector(".stApp");
        const boxes = app ? app.querySelectorAll('[class*="st-key-pbchart_"]') : [];
        let style = null;
        boxes.forEach(function (box) {{
          const gd = box.querySelector(".js-plotly-plot"), mark = box.querySelector(".mh-clock");
          let layer = gd ? gd.querySelector(":scope > .mh-cover") : null;
          if (!gd || !gd._fullLayout || (mark && mark.dataset.done)) {{ if (layer) layer.remove(); return; }}
          if (!mark) {{                     // a rerun is redrawing the marker: hold the cover where it is, briefly
            if (layer && !layer.dataset.lost) layer.dataset.lost = String(now);
            if (layer && now - +layer.dataset.lost > 1500) layer.remove();
            return;
          }}
          if (layer) delete layer.dataset.lost;
          if (!mark.dataset.t0) {{                // data-sent may lie ahead: the playback holds its first frame
            const late = Date.now() - (+mark.dataset.sent || Date.now());
            mark.dataset.t0 = String(now - (late > -5000 && late < 2000 ? late : 0));
          }}
          if (mark.dataset.wait && !mark.dataset.asked) {{   // the playback waits for this chart: it is drawn
            const ready = document.querySelector(".st-key-mh_pb_ready button");
            if (ready) {{ mark.dataset.asked = "1"; ready.click(); }}
          }}
          const from = +mark.dataset.from, to = +mark.dataset.to, secs = +(mark.dataset.secs || 0);
          const f = Math.max(0, Math.min(1, (now - +mark.dataset.t0) / (secs * 1000)));
          const clock = secs > 0 ? from + (to - from) * f : from;
          style = style || getComputedStyle(app);
          const fl = gd._fullLayout, bg = style.backgroundColor, ink = style.color;
          const axes = Object.keys(fl).filter((k) => /^xaxis\\d*$/.test(k)).sort();
          const sig = [fl.width, fl.height, bg, ink, axes.length].join("|");
          if (!layer || layer.dataset.sig !== sig) {{                  // (re)build one cover per panel
            if (!layer) {{
              layer = document.createElement("div"); layer.className = "mh-cover"; gd.appendChild(layer);
              if (getComputedStyle(gd).position === "static") gd.style.position = "relative";
            }}
            layer.dataset.sig = sig; layer.replaceChildren();
            axes.forEach(function (k, i) {{
              const r = document.createElement("div");
              r.style.cssText = "position:absolute;z-index:1;pointer-events:auto;background:" + bg +
                ";border-left:1.5px solid color-mix(in srgb, " + ink + " 70%, transparent)";
              if (i === 0) {{
                const t = document.createElement("div");
                t.style.cssText = "position:absolute;left:6px;top:4px;font-size:12px;white-space:nowrap;color:" + ink;
                r.appendChild(t);
              }}
              layer.appendChild(r);
            }});
          }}
          axes.forEach(function (k, i) {{
            const xa = fl[k], ya = fl["yaxis" + String(xa.anchor || "y").slice(1)], r = layer.children[i];
            if (!ya || !r || typeof xa.l2p !== "function") return;
            const x = Math.max(0, Math.min(xa._length, xa.l2p(clock)));
            r.style.left = (xa._offset + x) + "px"; r.style.width = Math.max(0, xa._length - x + 3) + "px";
            r.style.top = (ya._offset - 3) + "px"; r.style.height = (ya._length + 6) + "px";   // 3 px past the edges
            if (i === 0) r.firstChild.textContent = label(clock);
          }});
        }});
      }} catch (e) {{}}
      requestAnimationFrame(covers);
    }}
    requestAnimationFrame(covers);
    setInterval(function () {{
      try {{
        if (ls && window.__mhTheme.adopted) {{        // remember the latest Settings-menu choice for other pages
          const c = ls.getItem(KEY(window.__mhTheme.path)); if (c) ls.setItem("mh-theme", c);
        }}
        const app = document.querySelector(".stApp");
        const tag = document.getElementById("mh-theme-sync");
        if (!app || !tag) return;
        const m = getComputedStyle(app).backgroundColor.match(/\\d+(\\.\\d+)?/g);
        if (!m) return;
        const lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
        const actual = lum > 0.5 ? "light" : "dark";
        if (actual === tag.dataset.mode) {{ window.__mhTheme.asked = null; return; }}
        if (window.__mhTheme.asked === actual) return;   // asked once for this theme already
        const btn = document.querySelector(".st-key-{key} button");
        if (btn) {{ window.__mhTheme.asked = actual; btn.click(); }}
      }} catch (e) {{}}
    }}, 400);
  }}
}})();
</script>
"""


def apply() -> None:
    """Inject the CSS block and the page script (one element, placed before the hidden button so the button is
    hidden from the first paint). Call once per page; ui.setup_page() does."""
    st.html(CSS + _SCRIPT.format(mode=palette.current_mode(), key=SYNC_KEY), unsafe_allow_javascript=True)
    # hidden (and blank, in case a page change shows it for a frame); the script clicks it to redraw the charts
    st.button(chr(0x200B), key=SYNC_KEY, type="tertiary")     # label: a zero-width space
