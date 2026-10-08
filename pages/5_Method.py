"""Method: what is modelled, ground truth, policies, statistics, the extensions and the limitations.
Text is read from README.md, experiments/analyze.py and results/extensions/EXTENSIONS.md so it cannot drift."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app_lib import results_io as io
from app_lib import ui

ui.setup_page()
st.title("Method")
st.caption("Read from README.md, the module docstring of experiments/analyze.py, results/dev/calibration.json and "
           "results/extensions/EXTENSIONS.md.")


def readme(heading):
    try:
        txt = io.readme_section(heading)
        st.markdown(txt if txt else f"_Section '{heading}' not found in README.md._")
    except io.ResultsMissing as e:
        st.error(str(e))


main, ext, app = st.tabs(["Main study", "Extensions", "How this app works"])
with main:
    st.header("What is modelled")
    readme("What is modelled")
    st.header("Policies")
    readme("Policies")
    st.header("Ground truth")
    readme("Ground truth")
    st.header("Metrics on the run pages")
    st.table(pd.DataFrame([
        ("Detected (T_det)", "first alarm of the policy, seconds after the disturbance started"),
        ("Declared recovered (T_decl)", "time of the policy's final recovery declaration after the disturbance ended"),
        ("State converged (T_conv)", "residue zero and tips on one chain, held for 10 s"),
        ("Backlog recovered (T_bk)", "pending set no larger than the clean history's, held for 10 s"),
        ("FRE_state / FRE", "seconds reported 'recovered' while residue (FRE_state) or residue or backlog debt (FRE) "
                            "remained"),
        ("Residue at declaration", "residue transactions at the moment recovery was declared"),
        ("Recovery traffic", "announce/request 36 B per id and 250 B per transaction transferred"),
    ], columns=["Metric", "Definition"]))
    st.header("Statistics")
    try:
        st.text(io.module_docstring("experiments/analyze.py"))
    except FileNotFoundError:
        st.info("experiments/analyze.py not found.")
    st.header("Calibration (dev seeds 0–4 only)")
    try:
        cal = io.load_json("calibration")
        st.text(io.module_docstring("experiments/calibrate.py"))
        st.table(pd.DataFrame([{"parameter": k, "value": v} for k, v in cal["values"].items()]))
    except io.ResultsMissing as e:
        st.error(str(e))
    st.header("Limitations")
    readme("Limitations to state in the paper")

with ext:
    st.info("The extensions are separate experiments. They never change the main study; every model feature they "
            "added is off by default (with defaults every run is bit-for-bit identical to the main study's).")
    readme("Extensions")
    try:
        secs = io.md_sections(io.load_text("extensions_md"))
    except io.ResultsMissing as e:
        st.error(str(e))
        st.stop()
    pre = secs.get("preregistration", "")
    limits = io.discussion_limits(secs.get("discussion", ""))
    for key, title in (("Extension A", "Extension A: confirmation delay and block composition"),
                       ("Extension B", "Extension B: scale and topology"),
                       ("Extension C", "Extension C: bounded mempools and eviction")):
        st.header(title)
        st.markdown(io.md_subsection(pre, key) or "_Definition not found in EXTENSIONS.md._")
        lim = next((v for k, v in limits.items() if k.startswith(key)), None)
        if lim:
            st.markdown(f"**Limitations.** {lim}")
    st.header("Common rules and limitations")
    st.markdown(pre.split("### Extension A")[0].split("\n", 1)[-1] if "### Extension A" in pre else "")
    if "Common limitations" in limits:
        st.markdown(f"**Common limitations.** {limits['Common limitations']}")
    st.header("Changes after pre-registration")
    st.markdown(secs.get("changelog", "").replace("## Change log", "", 1))

with app:
    st.markdown("""
- **Live runs are the study pipeline.** The Simulator, Policy comparison and Network replay pages call
  `mh.runner.run_one` exactly as `demo.py` does: the clean B1 history first (its pending-set series is the backlog
  counterfactual), then each policy on the same seed. Runs are deterministic, so with the study settings a held-out
  seed reproduces the stored study run. The app only imports `mh/`; it never changes it.
- **Settings.** The sidebar starts from the calibrated configuration (`mh.calibration.load_config()`). Changing any
  setting applies to a copy (the configuration object is immutable) and marks the run *exploratory, not part of the
  study*. A longer disturbance extends the run so the 600 s after it stay observable. "Hold block-space utilisation"
  scales block capacity with the transaction rate, as Extension B does.
- **Extension metrics on the run pages** (confirmation delay, excess delay against the paired clean history,
  block-composition distance, and with a mempool cap evicted-divergence and evictions) are computed with
  `mh/ext_metrics.py`, the same functions the extension experiments used.
- **Network replay.** The run is simulated once with a read-only snapshot callback every few simulated seconds,
  scheduled just after the evaluator's own sample, so the residue per frame is the evaluator's residue at that instant.
  Link states are derived from the disturbance description; the monitor's view is read from the shared monitor.
- **Stored results.** The Study results page only reads `results/numbers.json`, `results/sweeps.json`,
  `results/verification.json`, `results/extensions/ext_numbers.json` and `EXTENSIONS.md`; no number is recomputed.
- **Caching.** Each run is cached on (seed, disturbance, policy, settings), so revisiting a selection is instant.
""")
