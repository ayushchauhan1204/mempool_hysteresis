"""Extension hand verification ('verify before trusting', as experiments/verify_by_hand.py does for the main study).

Deliberately naive code that shares nothing with mh/ext_metrics.py or the eviction code in mh/sim.py:
  1. Confirmation delay: for seed 1000 / partition / B1 and its paired clean history, rebuild the final best chain
     by walking parent pointers from the best tip, find each transaction's block by linear search, and recompute
     the window statistics, excess delay and block-composition distance; compare with the pipeline row stored in
     results/extensions/ext_a_runs.csv.
  2. Eviction: in one capped run (seed 3000, burst, B1, cap level "mid"), check every admission decision taken at
     one node while its mempool was full or its minimum fee was raised, at the moment it happened, against the
     rule written in EXTENSIONS.md; and recompute the evicted-divergence count from raw state dumps at three
     checkpoints.
Output: results/extensions/verification_ext.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mh.calibration import load_config  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402
from mh.policies import make_policy  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402
from mh.sim import Simulation  # noqa: E402

OUT = ROOT / "results" / "extensions"


# ------------------------------------------------------------------------------ 1. confirmation delay
def naive_best_tip(sim):
    tips = list(sim.tip)
    best = None
    for t in tips:
        key = (sim.blocks[t].height, tips.count(t), -t)
        if best is None or key > best[0]:
            best = (key, t)
    return best[1]


def naive_chain(sim):
    chain = []
    bid = naive_best_tip(sim)
    while bid != 0:
        blk = sim.blocks[bid]
        chain.append((blk.time, list(blk.txs)))
        bid = blk.parent
    return chain


def naive_conf_time(chain, x):
    for t, txs in chain:
        for y in txs:
            if y == x:
                return t
    return None


def naive_quantile(values, q):
    v = sorted(values)
    if not v:
        return float("nan")
    pos = q * (len(v) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def check_confirmation():
    cfg = load_config()
    seed, dist, pol = 1000, "partition", "B1"
    t0, te, horizon = cfg.dist_start, cfg.t_end(dist), cfg.horizon
    cutoffs = sorted({cfg.t_end(d) for d in DISTURBANCES})
    ref = run_one(cfg, seed, None, "B1", cutoffs=cutoffs, keep_log=True)
    run = run_one(cfg, seed, dist, pol, keep_log=True, pend_ref=ref["series"]["pend"])
    sim_c, sim_d = ref["sim"], run["sim"]
    chain_c, chain_d = naive_chain(sim_c), naive_chain(sim_d)
    created = list(sim_d.scn.created)
    base = list(sim_d.scn.is_base)
    win = {"before": (t0 - 120.0, t0), "during": (t0, te), "after": (te, te + 300.0),
           "exposed": (t0 - 120.0, te + 300.0)}
    hand = {}
    for name, (lo, hi) in win.items():
        ids = [x for x in range(len(created)) if base[x] and lo <= created[x] < hi]
        delays, never, excess = [], 0, []
        for x in ids:
            cd = naive_conf_time(chain_d, x)
            cc = naive_conf_time(chain_c, x)
            dd = (cd - created[x]) if cd is not None else None
            dc = (cc - created[x]) if cc is not None else None
            if dd is None:
                never += 1
            else:
                delays.append(dd)
            excess.append((dd if dd is not None else horizon - created[x]) -
                          (dc if dc is not None else horizon - created[x]))
        hand[name] = dict(n=len(ids), never=never, mean=sum(delays) / len(delays), median=naive_quantile(delays, .5),
                          p95=naive_quantile(delays, .95), x_mean=sum(excess) / len(excess))
    cd_set, cc_set = set(), set()
    for t, txs in chain_d:
        if te <= t < te + 300.0:
            cd_set.update(x for x in txs if base[x])
    for t, txs in chain_c:
        if te <= t < te + 300.0:
            cc_set.update(x for x in txs if x < len(base) and base[x])
    union = cd_set | cc_set
    hand_bcd = 1 - len(cd_set & cc_set) / len(union)

    stored = pd.read_csv(OUT / "ext_a_runs.csv")
    row = stored[(stored["sample"] == "heldout") & (stored.seed == seed) & (stored.dist == dist) &
                 (stored.policy == pol)].iloc[0]
    comp = []
    for name, h in hand.items():
        for k, v in h.items():
            col = f"{name}_{k}" if k != "x_mean" else f"{name}_x_mean"
            p = float(row[col])
            comp.append(dict(quantity=col, hand=v, pipeline=p, match=bool(abs(v - p) <= 1e-9 * max(1.0, abs(v)))))
    comp.append(dict(quantity="blk_bcd", hand=hand_bcd, pipeline=float(row["blk_bcd"]),
                     match=bool(abs(hand_bcd - float(row["blk_bcd"])) <= 1e-12)))
    return dict(seed=seed, dist=dist, policy=pol, checks=comp, all_match=all(c["match"] for c in comp))


# ------------------------------------------------------------------------------ 2. eviction
def naive_decision(fee_x, held, min_fee, cap):
    """held: list of (fee, tx) pending at the node before the arrival. Returns (accepted, evicted tx, new min fee)."""
    if fee_x < min_fee:
        return False, None, min_fee
    if len(held) >= cap:
        low_fee, low_tx = min(held)
        if fee_x > low_fee:
            return True, low_tx, max(min_fee, low_fee)
        return False, None, max(min_fee, fee_x)
    return True, None, min_fee


def dump(sim, store, label):
    store[label] = dict(t=sim.now, mempool=[set(m) for m in sim.mempool], conf=[set(c) for c in sim.conf],
                        dropped=[set(d) for d in sim.dropped])


def naive_evdiv(state, created, t_end, tau_m):
    cut = min(t_end, state["t"] - tau_m)
    n = len(state["mempool"])
    pending = set()
    for m in state["mempool"]:
        pending |= m
    count = 0
    for x in sorted(pending):
        if not created[x] < cut:
            continue
        if any(x not in state["mempool"][j] and x not in state["conf"][j] and x in state["dropped"][j]
               for j in range(n)):
            count += 1
    return count


def check_eviction():
    cfg0 = load_config()
    caps = json.loads((OUT / "ext_c_cap_calibration.json").read_text())["caps"]
    cap = int(caps["mid"])
    cfg = cfg0.with_(mempool_cap=cap)
    seed, dist, node = 3000, "burst", 0
    te = cfg.t_end(dist)
    scn = build_scenario(cfg, seed, dist)
    sim = Simulation(scn, make_policy("B1"), cutoffs=[te])
    events = []
    original = sim._admit

    def watched(i, x):
        if i != node:
            return original(i, x)
        held = [(sim.fee[y], y) for y in sim.mempool[i]]
        before_min = sim.min_fee[i]
        before = set(sim.mempool[i])
        ok = original(i, x)
        evicted = list(before - set(sim.mempool[i]))
        if len(held) >= cap or before_min > 0:
            exp_ok, exp_ev, exp_min = naive_decision(sim.fee[x], held, before_min, cap)
            events.append(dict(t=sim.now, tx=x, fee=sim.fee[x], held=len(held), min_fee_before=before_min,
                               accepted=ok, evicted=evicted, min_fee_after=sim.min_fee[i],
                               match=bool(ok == exp_ok and evicted == ([exp_ev] if exp_ev is not None else [])
                                          and sim.min_fee[i] == exp_min)))
        return ok

    sim._admit = watched
    dumps = {}
    checkpoints = [te + 10.0, te + 60.0, te + 300.0]
    for c in checkpoints:
        sim.at(c + 1e-9, dump, sim, dumps, c)
    sim.run()
    t = np.asarray(sim.series["t"])
    ev = np.asarray(sim.series[f"evdiv@{te:g}"])
    evdiv_rows = []
    for c in checkpoints:
        hand = naive_evdiv(dumps[c], scn.created.tolist(), te, cfg.tau_m)
        k = int(np.argmin(np.abs(t - c)))
        evdiv_rows.append(dict(t_after_end=c - te, hand=hand, pipeline=int(ev[k]), match=hand == int(ev[k])))
    n_ev = sum(len(e["evicted"]) for e in events)
    return dict(seed=seed, dist=dist, policy="B1", cap_level="mid", cap=cap, node=node,
                decisions_checked=len(events), evictions_checked=n_ev,
                rejections_checked=sum(1 for e in events if not e["accepted"]),
                all_decisions_match=all(e["match"] for e in events),
                examples=[e for e in events if e["evicted"]][:3] + [e for e in events if not e["accepted"]][:2],
                evicted_divergence_checks=evdiv_rows,
                evdiv_all_match=all(r["match"] for r in evdiv_rows))


def main():
    rep = dict(confirmation_delay=check_confirmation(), eviction=check_eviction())
    rep["all_match"] = (rep["confirmation_delay"]["all_match"] and rep["eviction"]["all_decisions_match"]
                        and rep["eviction"]["evdiv_all_match"])
    (OUT / "verification_ext.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({k: (v if k == "all_match" else {kk: vv for kk, vv in v.items()
                                                      if kk not in ("checks", "examples")})
                      for k, v in rep.items()}, indent=1, default=float))


if __name__ == "__main__":
    main()
