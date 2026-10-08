"""Phase 3 calibration on dev seeds 0-4 only (plan Section 7).

  tau_m  = 1.5 x 99.9th percentile of clean end-to-end propagation time
  eps_D  = 99.5th percentile of clean audit divergence D; SARA floors it at the
           measurement resolution 2 / (N * |R|) at every audit (one unknown
           transaction at one node), so it never divides by zero
  beta   = smallest of {99.5th, 99.9th percentile, max} of clean backlog B whose
           replayed false-incident rate is below 0.1 per clean run
  eps_size (-D proxy) chosen the same way, given beta

Observation runs use infinite limits, so no alarm or action perturbs the clean state.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mh.config import SimConfig  # noqa: E402
from mh.policies import make_policy  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402
from mh.sim import Simulation  # noqa: E402

DEV_SEEDS = [0, 1, 2, 3, 4]
OUT = Path(__file__).resolve().parents[1] / "results" / "dev"
MAX_FALSE_PER_RUN = 0.1


def replay_false_incidents(ratio_series, debounce):
    """Count incidents a debounced detector would open on a clean series of risk ratios."""
    n = 0
    streak = 0
    is_open = False
    for r in ratio_series:
        streak = streak + 1 if r >= 1 else 0
        if not is_open and streak >= debounce:
            is_open = True
            n += 1
        elif is_open and r < 1:
            is_open = False
    return n


def main():
    report = calibrate(SimConfig(), DEV_SEEDS)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calibration.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


def calibrate(cfg0, dev_seeds=DEV_SEEDS):
    """Calibrate tau_m, eps_D, beta and eps_size for configuration cfg0 on dev seeds only."""
    DEV = list(dev_seeds)
    # 1. maturity from clean propagation times
    props = []
    for seed in DEV:
        scn = build_scenario(cfg0, seed, None)
        sim = Simulation(scn, make_policy("B1")).run()
        created = scn.created
        for x in range(len(created)):
            if created[x] < cfg0.horizon - 30.0:
                ts = [sim.seen[i].get(x) for i in range(sim.n)]
                if all(v is not None for v in ts):
                    props.append(max(ts) - created[x])
    props = np.asarray(props)
    q999 = float(np.quantile(props, 0.999))
    tau_m = round(1.5 * q999, 2)

    # 2. observation runs with infinite limits
    inf = math.inf
    obs_cfg = cfg0.with_(tau_m=tau_m, eps_D=inf, beta=inf, eps_size=inf)
    D, B, NR, P, PB = [], [], [], [], []
    per_run_B, per_run_P = [], []
    for seed in DEV:
        r = run_one(obs_cfg, seed, None, "SARA", cutoffs=[360.0], keep_series=False)
        a = r["audit_log"]
        a = a[a[:, 0] >= cfg0.eval_start]
        D += a[:, 1].tolist()
        B += a[:, 2].tolist()
        NR += a[:, 8].tolist()
        per_run_B.append(a[:, 2])
        rd = run_one(obs_cfg, seed, None, "SARA-D", cutoffs=[360.0], keep_series=False)
        ad = rd["audit_log"]
        ad = ad[ad[:, 0] >= cfg0.eval_start]
        P += ad[:, 1].tolist()
        per_run_P.append((ad[:, 1], ad[:, 2]))
    D, B, NR, P = map(np.asarray, (D, B, NR, P))
    n = cfg0.n_nodes
    resolution = 2.0 / (n * float(np.median(NR)))   # reported only; SARA applies it per audit
    q995_D = float(np.quantile(D, 0.995))
    eps_D = q995_D

    def choose(values, per_run_ratio_fn):
        tried = []
        for name, q in (("q99.5", 0.995), ("q99.9", 0.999), ("max", 1.0)):
            lim = float(np.quantile(values, q)) if q < 1 else float(np.max(values)) * 1.0001
            fa = np.mean([replay_false_incidents(per_run_ratio_fn(i, lim), cfg0.open_debounce)
                          for i in range(len(DEV))])
            tried.append(dict(rule=name, limit=lim, false_incidents_per_run=float(fa)))
            if fa < MAX_FALSE_PER_RUN:
                return lim, tried
        return tried[-1]["limit"], tried

    beta, beta_tried = choose(B, lambda i, lim: per_run_B[i] / lim)
    eps_size, size_tried = choose(P, lambda i, lim: np.maximum(per_run_P[i][0] / lim, per_run_P[i][1] / beta))

    values = dict(tau_m=tau_m, eps_D=eps_D, beta=beta, eps_size=eps_size)
    report = dict(
        values=values,
        dev_seeds=DEV,
        propagation=dict(n=int(len(props)), q50=float(np.quantile(props, .5)), q99=float(np.quantile(props, .99)),
                         q999=q999, max=float(props.max())),
        divergence=dict(n_audits=int(len(D)), frac_nonzero=float(np.mean(D > 0)), q995=q995_D,
                        max=float(D.max()), median_R=float(np.median(NR)), resolution=resolution),
        backlog=dict(q50=float(np.quantile(B, .5)), q995=float(np.quantile(B, .995)),
                     q999=float(np.quantile(B, .999)), max=float(B.max()), tried=beta_tried),
        size_proxy=dict(q50=float(np.quantile(P, .5)), q995=float(np.quantile(P, .995)),
                        q999=float(np.quantile(P, .999)), max=float(P.max()), tried=size_tried),
    )
    return report


if __name__ == "__main__":
    main()
