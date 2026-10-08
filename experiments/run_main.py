"""Phase 4 main evaluation on held-out seeds (never used for calibration).

Per seed: the clean history (B1, SARA, SARA-D, SARA-R, SARA-V) and every disturbance
type under all six policies. Results land in results/raw/main/seed_XXXXX.pkl.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.common import run_many  # noqa: E402
from mh.calibration import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=1000)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "results" / "raw" / "main"))
    args = ap.parse_args()
    cfg = load_config()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "config.json").write_text(json.dumps(cfg.as_dict(), indent=1))
    seeds = list(range(args.first, args.first + args.n))
    print(f"held-out seeds {seeds[0]}..{seeds[-1]}  config tau_m={cfg.tau_m} beta={cfg.beta:.3f} "
          f"eps_size={cfg.eps_size} eps_D={cfg.eps_D}", flush=True)
    run_many(seeds, cfg, args.out)
    print("done", flush=True)
