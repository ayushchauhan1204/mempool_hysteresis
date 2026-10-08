"""Phase 1 generator sanity checks (plan Section 3). Dev seeds only.

1. Clean run: every transaction reaches every node; no mature knowledge divergence;
   tips agree except briefly; state invariants hold (seen == mempool | confirmed).
2. Partition run: both sides mine; the fork resolves after reconnection; the reorg
   returns transactions to the losing side's mempools.
3. Cross-tab of residue at t_end + 10 s by disturbance type on the no-intervention
   network (B1); the burst should raise backlog instead.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mh.config import DISTURBANCES, SimConfig  # noqa: E402
from mh.policies import make_policy  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402
from mh.sim import Simulation  # noqa: E402

DEV_SEEDS = [0, 1, 2, 3, 4]
OUT = Path(__file__).resolve().parents[1] / "results" / "dev"


def invariants(sim):
    bad = 0
    for i in range(sim.n):
        mp = set(sim.mempool[i])
        cf = sim.conf[i]
        seen = set(sim.seen[i])
        if mp & cf:
            bad += 1
        if seen != (mp | cf):
            bad += 1
        # confirmed set equals union of active-chain block contents
        chain_txs = set()
        for bid in sim.chain[i]:
            chain_txs.update(sim.blocks[bid].txs)
        if chain_txs != cf:
            bad += 1
    return bad


def check_clean(cfg):
    out = []
    for seed in DEV_SEEDS:
        scn = build_scenario(cfg, seed, None)
        sim = Simulation(scn, make_policy("B1"), cutoffs=[360.0]).run()
        created = scn.created
        last = cfg.horizon - 30.0
        ids = [x for x in range(len(created)) if created[x] < last]
        missing = sum(1 for x in ids for i in range(sim.n) if x not in sim.seen[i])
        prop = np.array([max(sim.seen[i][x] for i in range(sim.n)) - created[x] for x in ids
                         if all(x in sim.seen[i] for i in range(sim.n))])
        s = sim.series
        chain_ok = np.asarray(s["chain_ok"], bool)
        out.append(dict(seed=seed, txs=len(ids), missing_node_tx_pairs=int(missing),
                        prop_q50=float(np.quantile(prop, .5)), prop_q99=float(np.quantile(prop, .99)),
                        prop_q999=float(np.quantile(prop, .999)), prop_max=float(prop.max()),
                        max_U=int(np.max(s["U"])), max_D=float(np.max(s["D"])),
                        chain_ok_frac=float(chain_ok.mean()), stale=sim.c["mined"] - sim.blocks[sim.best_tip()[0]].height,
                        mined=sim.c["mined"], invariant_violations=invariants(sim),
                        mean_B=float(np.mean(s["B"])), max_B=float(np.max(s["B"]))))
    return out


def check_partition(cfg):
    out = []
    for seed in DEV_SEEDS:
        scn = build_scenario(cfg, seed, "partition")
        sim = Simulation(scn, make_policy("B1"), cutoffs=[360.0]).run()
        A = set(scn.disturbance.group_a)
        d0, d1 = scn.disturbance.start, scn.disturbance.end
        mined_a = mined_b = 0
        for b in sim.blocks[1:]:
            if d0 <= b.time < d1:
                if b.miner in A:
                    mined_a += 1
                else:
                    mined_b += 1
        t = np.asarray(sim.series["t"])
        ntips = np.asarray(sim.series["n_tips"])
        ok = np.asarray(sim.series["chain_ok"], bool)
        after = t >= d1
        first_ok = float(t[after][np.argmax(ok[after])] - d1) if ok[after].any() else None
        out.append(dict(seed=seed, group_a=sorted(A), mined_side_a=mined_a, mined_side_b=mined_b,
                        max_tips_during=int(ntips[(t >= d0) & (t < d1)].max()),
                        chain_ok_after_s=first_ok, reorgs=sim.c["reorgs"],
                        reorg_returned=sim.c["reorg_returned"], invariant_violations=invariants(sim)))
    return out


def crosstab(cfg):
    rows = []
    for dist in DISTURBANCES:
        for seed in DEV_SEEDS:
            r = run_one(cfg, seed, dist, "B1")
            te = cfg.t_end(dist)
            m = r["metrics"][f"{te:g}"]
            s = r["series"]
            t = np.asarray(s["t"])
            pre = (t >= 240) & (t < cfg.dist_start)
            dur = (t >= cfg.dist_start) & (t < te)
            rows.append(dict(dist=dist, seed=seed, resid_10=m["resid_10"], resid_60=m["resid_60"],
                             T_conv=m["T_conv"], T_decl_B1=m["T_decl"], B_pre=float(np.mean(s["B"][pre])),
                             B_max_during_after=float(np.max(s["B"][t >= cfg.dist_start])),
                             reorg_returned=r["chain"]["reorg_returned"], stale=r["chain"]["stale_rate"]))
    return rows


if __name__ == "__main__":
    cfg = SimConfig()
    OUT.mkdir(parents=True, exist_ok=True)
    res = dict(clean=check_clean(cfg), partition=check_partition(cfg), crosstab=crosstab(cfg))
    (OUT / "sanity.json").write_text(json.dumps(res, indent=1, default=float))
    print("== clean ==")
    for r in res["clean"]:
        print(r)
    print("== partition ==")
    for r in res["partition"]:
        print(r)
    print("== residue cross-tab (B1, no intervention) ==")
    import collections
    agg = collections.defaultdict(list)
    for r in res["crosstab"]:
        agg[r["dist"]].append(r)
    for d, rs in agg.items():
        print(f"{d:11s} resid@+10s={[r['resid_10'] for r in rs]}  resid@+60s={[r['resid_60'] for r in rs]}  "
              f"T_conv={[round(r['T_conv']) for r in rs]}  B_pre={np.mean([r['B_pre'] for r in rs]):.2f} "
              f"B_max={np.mean([r['B_max_during_after'] for r in rs]):.2f}")
