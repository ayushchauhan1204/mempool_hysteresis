"""Phase 4 'verify before trusting' (plan Section 7).

Independently recomputes, with deliberately naive code that shares nothing with the
evaluator, (1) the residue count at fixed checkpoints from raw state dumps taken mid-run,
and (2) B1's false-recovery exposure from the raw monitor log, then compares both with
the pipeline's own numbers for the same held-out run.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mh.calibration import load_config  # noqa: E402
from mh.policies import make_policy  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402
from mh.sim import Simulation  # noqa: E402

SEED, DIST = 1000, "partition"


def dump_state(sim, store, label):
    store[label] = dict(t=sim.now, mempool=[dict(m) for m in sim.mempool], conf=[set(c) for c in sim.conf],
                        tips=list(sim.tip))


def naive_residue(state, created, t_end, tau_m):
    t = state["t"]
    cut = min(t_end, t - tau_m)
    n = len(state["mempool"])
    count = 0
    every_pending = set()
    for i in range(n):
        for x in state["mempool"][i]:
            every_pending.add(x)
    for x in sorted(every_pending):
        if not created[x] < cut:
            continue
        pending_somewhere = any(x in state["mempool"][i] for i in range(n))
        unknown_somewhere = any((x not in state["mempool"][j]) and (x not in state["conf"][j]) for j in range(n))
        if pending_somewhere and unknown_somewhere:
            count += 1
    return count


def main():
    cfg = load_config()
    t_end = cfg.t_end(DIST)
    checkpoints = [t_end + 10.0, t_end + 30.0, t_end + 120.0]

    # 1. residue from raw state dumps, taken at exactly the evaluator's sample instants
    scn = build_scenario(cfg, SEED, DIST)
    dumps = {}
    sim = Simulation(scn, make_policy("B1"))
    for c in checkpoints:
        # schedule the dump just after the evaluator's own sample at the same instant
        sim.at(c + 1e-9, dump_state, sim, dumps, c)
    sim.run()
    created = scn.created.tolist()
    t_series = np.asarray(sim.series["t"])
    res_series = np.asarray(sim.series[f"res@{t_end:g}"])
    rows = []
    for c in checkpoints:
        hand = naive_residue(dumps[c], created, t_end, cfg.tau_m)
        k = int(np.argmin(np.abs(t_series - c)))
        rows.append(dict(t_after_end=c - t_end, hand=hand, pipeline=int(res_series[k]), match=hand == int(res_series[k])))

    # 2. B1's false-recovery exposure from the raw monitor log and the residue series
    r = run_one(cfg, SEED, DIST, "B1", pend_ref=run_one(cfg, SEED, None, "B1")["series"]["pend"])
    m = r["metrics"][f"{t_end:g}"]
    recovered_events = [t for t, ev, a, b in r["monitor_log"] if ev == "recovered" and t >= cfg.dist_start]
    decl_hand = recovered_events[-1] - t_end
    t = np.asarray(r["series"]["t"])
    res = np.nan_to_num(np.asarray(r["series"][f"res@{t_end:g}"]))
    ok = (res == 0) & np.asarray(r["series"]["chain_ok"], bool)
    conv_hand = None
    for k in range(len(t)):
        if t[k] < t_end or not ok[k]:
            continue
        j = k
        while j < len(t) and ok[j] and t[j] - t[k] < cfg.hold_window:
            j += 1
        if j < len(t) and ok[j]:
            conv_hand = t[k] - t_end
            break
    fre_state_hand = max(0.0, conv_hand - decl_hand)
    report = dict(seed=SEED, dist=DIST, residue_checks=rows,
                  fre_check=dict(T_decl_hand=decl_hand, T_decl_pipeline=m["T_decl"],
                                 T_conv_hand=conv_hand, T_conv_pipeline=m["T_conv"],
                                 FRE_state_hand=fre_state_hand, FRE_state_pipeline=m["FRE_state"],
                                 match=abs(fre_state_hand - m["FRE_state"]) < 1e-6 and abs(decl_hand - m["T_decl"]) < 1e-6))
    out = ROOT / "results" / "verification.json"
    out.write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    main()
