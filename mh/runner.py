"""Run one simulation and package everything needed downstream into a plain dict."""
from __future__ import annotations

import math
import time

import numpy as np

from .config import SimConfig
from .metrics import run_metrics
from .policies import make_policy
from .scenario import build_scenario
from .sim import Simulation


def run_one(cfg: SimConfig, seed: int, dist: str | None, policy: str,
            cutoffs=None, keep_series=True, keep_log=False, pend_ref=None) -> dict:
    """Simulate (seed, disturbance, policy). For a clean run pass dist=None and the cutoffs
    (t_end values) of the disturbed runs it will be paired with."""
    t0 = time.perf_counter()
    if cutoffs is None:
        cutoffs = [cfg.t_end(dist)]
    scn = build_scenario(cfg, seed, dist, t_end=cutoffs[0])
    sim = Simulation(scn, make_policy(policy), cutoffs=cutoffs)
    sim.run()

    # final best chain -> confirmation times
    best, _ = sim.best_tip()
    conf_time = {}
    b = sim.blocks[best]
    while b.id != 0:
        for x in b.txs:
            conf_time[x] = b.time
        b = sim.blocks[b.parent]
    best_h = sim.blocks[best].height
    mined = sim.c["mined"]

    created = scn.created
    post = {}
    for c in cutoffs:
        ids = np.nonzero(scn.is_base & (created >= c) & (created < c + cfg.post_workload_window))[0]
        conf_lat = np.array([conf_time.get(int(x), math.nan) - created[x] for x in ids])
        cens_lat = cfg.horizon - created[ids]
        prop = []
        for x in ids:
            x = int(x)
            ts = [sim.seen[i].get(x) for i in range(sim.n)]
            prop.append(max(ts) - created[x] if all(v is not None for v in ts) else math.nan)
        post[f"{c:g}"] = dict(ids=ids.astype(np.int32), conf_latency=conf_lat.astype(np.float64),
                             cens_latency=cens_lat, prop_latency=np.array(prop))

    pol = sim.policy.summary()
    out = dict(
        seed=seed, dist=dist, policy_name=policy, cutoffs=list(cutoffs),
        policy=pol,
        chain=dict(best_height=best_h, mined=mined,
                   stale_rate=(mined - best_h) / mined if mined else 0.0,
                   reorgs=sim.c["reorgs"], reorg_returned=sim.c["reorg_returned"]),
        counters=dict(sim.c),
        post_workload=post,
        series={k: (np.asarray(v, dtype=np.float32) if k != "chain_ok" else np.asarray(v, bool))
                for k, v in sim.series.items()},
        monitor_log=list(sim.monitor_log),
        wall=time.perf_counter() - t0,
    )
    if hasattr(sim.policy, "audit_log"):
        out["audit_log"] = np.asarray(sim.policy.audit_log, dtype=np.float64) if sim.policy.audit_log else np.zeros((0, 9))
    if keep_log:
        out["log"] = list(sim.policy.log)
        out["sim"] = sim
    if pend_ref is None and dist is None:
        pend_ref = out["series"]["pend"]          # a clean run is its own counterfactual
    out["metrics"] = {f"{c:g}": run_metrics(out, c, cfg, cfg.dist_start, pend_ref=pend_ref) for c in cutoffs}
    if not keep_series:
        out.pop("series")
    return out
