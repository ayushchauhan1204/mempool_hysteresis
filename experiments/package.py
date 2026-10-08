"""Bundle the working model: code, tests, README, calibration, numbers.json, tables and figures.
Raw per-seed pickles are excluded (regenerable with run_main.py / sweeps.py)."""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "mempool_hysteresis_working_model.zip"
INCLUDE_GLOBS = [
    "README.md", "demo.py", "mh/*.py", "experiments/*.py", "tests/*.py",
    "results/numbers.json", "results/sweeps.json", "results/RESULTS.md", "results/verification.json",
    "results/all_runs.csv", "results/dev/calibration.json", "results/dev/sanity.json",
    "results/dev/dev_check.txt", "results/figures/*.pdf", "results/figures/*.png", "results/demo_*.png",
    "results/raw/main/config.json",
    # extension experiments (raw per-job pickles in results/extensions/raw/ are excluded, as for the main study)
    "tests/regression_snapshot.json", "results/extensions/*.md", "results/extensions/*.json",
    "results/extensions/*.csv", "results/extensions/*.sha256", "results/extensions/*_log.txt",
    "results/extensions/figures/*.png", "results/extensions/figures/*.pdf",
    # frontend (streamlit run app.py)
    "app.py", "pages/*.py", "app_lib/*.py", ".streamlit/config.toml",
]

if __name__ == "__main__":
    files = []
    for g in INCLUDE_GLOBS:
        files += sorted(ROOT.glob(g))
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if "__pycache__" in f.parts:
                continue
            z.write(f, Path("mempool_hysteresis") / f.relative_to(ROOT))
    print(f"{OUT}  ({OUT.stat().st_size / 1e6:.1f} MB, {len(files)} files)")
