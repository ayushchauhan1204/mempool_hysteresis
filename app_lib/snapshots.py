"""Per-node mempool snapshots for the Network Replay page, without touching the simulator.

Same pattern as experiments/verify_by_hand.py: build a Simulation for (seed, disturbance, policy),
schedule a read-only callback every `interval` simulated seconds with ``sim.at``, run it, and keep
what the callback saw. The callback fires just after the evaluator's own sample at the same instant.

* Residue per frame uses mh.sim.residue_set with the evaluator's cutoff rule, so it equals the
  pipeline's res@t_end series at matching instants (checked in tests/test_app_lib.py).
* Link state per frame is derived from the scenario's disturbance object (start, end, groups, nodes)
  and the seed-fixed reconnection delay, not read from simulator internals.
* Policy, monitor and block events come from the logs and block list after the run.
* With a mempool cap (Extension C), each frame also records, per node, the distinct transactions evicted and
  rejected so far and the rolling minimum fee (read-only reads of the Simulation's attributes).
"""
from __future__ import annotations

import networkx as nx
import numpy as np

from .runs import _cache, make_config
from mh.policies import TIER_NAMES, make_policy
from mh.scenario import build_scenario, u01
from mh.sim import Simulation, residue_set

FRAME_EPS = 1e-9                 # fire just after the evaluator sample at the same instant
LINK_STATES = ("healthy", "cut", "reconnecting", "blackholed", "degraded")
LINK_STATE_HELP = {
    "healthy": "link up",
    "cut": "connection reset by the outage; messages lost",
    "reconnecting": "outage over, peers not yet reconnected",
    "blackholed": "traffic buffered or dropped in at least one direction",
    "degraded": "packet loss or added latency",
}


def link_state(cfg, scn, a: int, b: int, t: float) -> str:
    """True state of undirected link (a, b) at time t, derived from the disturbance description only."""
    d = scn.disturbance
    if d.kind is None or d.kind == "burst":
        return "healthy"
    if d.kind == "partition":
        grp = set(d.group_a)
        hit = (a in grp) != (b in grp)
    else:
        hit = a in d.nodes or b in d.nodes
    if not hit:
        return "healthy"
    during = d.start <= t < d.end
    if d.kind in ("partition", "isolation"):
        if cfg.outage_mode != "reset":
            return "blackholed" if during else "healthy"
        if during:
            return "cut"
        delay = u01((scn.seed, 31, min(a, b), max(a, b), 0)) * cfg.reconnect_max   # same draw as Simulation
        return "reconnecting" if d.end <= t < d.end + delay else "healthy"
    if not during:
        return "healthy"
    return "blackholed" if d.kind == "asymmetric" else "degraded"


def layout_positions(edges, n: int) -> dict:
    """Fixed node positions for the seed's topology (Kamada-Kawai: deterministic, no random start)."""
    g = nx.Graph()
    g.add_nodes_from(range(n))
    g.add_edges_from(edges)
    pos = nx.kamada_kawai_layout(g)
    return {int(i): (float(x), float(y)) for i, (x, y) in pos.items()}


def _snapshot(sim, frames, t, te, created, probe):
    cfg = sim.cfg
    mps, confs = sim.mempool, sim.conf
    union = set()
    for mp in mps:
        union.update(mp.keys())
    nu = len(union)
    if t + 60.0 < te:                      # the evaluator does not count residue this early (NaN)
        res = None
    else:
        res = residue_set(union, mps, confs, created, min(te, t - cfg.tau_m))
    pol = sim.policy
    frame = dict(
        t=t,
        pending=[len(mp) for mp in mps],
        union=nu,
        share=[(len(mp) / nu) if nu else 1.0 for mp in mps],
        residue=None if res is None else len(res),
        residue_ids=[] if res is None else sorted(res),
        lacks=[0] * sim.n if res is None else [len(res.difference(mp.keys()).difference(cf))
                                              for mp, cf in zip(mps, confs)],
        holds=[0] * sim.n if res is None else [len(res.intersection(mp.keys())) for mp in mps],
        heights=[sim.blocks[b].height for b in sim.tip],
        tips=list(sim.tip),
        chain_ok=bool(sim.chain_consistent()),
        mined=sim.c["mined"], reorgs=sim.c["reorgs"], reorg_returned=sim.c["reorg_returned"],
        monitor_unhealthy=[e for k, e in enumerate(sim.edges) if not sim.m_healthy[k]],
        status=pol.timeline[-1][1],
        tier=TIER_NAMES[pol.prev_tier] if hasattr(pol, "prev_tier") else None,
    )
    if getattr(sim, "cap", None) is not None:           # Extension C: per-node eviction and rejection so far
        ev, rj = [], []
        for d in sim.dropped:
            whys = [w for _, w in d.values()]
            ev.append(whys.count("evicted"))
            rj.append(whys.count("rejected"))
        frame.update(evicted=ev, rejected=rj, min_fee=[float(x) for x in sim.min_fee],
                     unrepairable=len(pol.unrepairable) if hasattr(pol, "unrepairable") else None)
    if probe is not None:
        frame["probe"] = probe(sim)
    frames.append(frame)


def compute_replay(seed: int, dist: str, policy: str, overrides: tuple = (), interval: float = 5.0,
                   t_from: float | None = None, probe=None) -> dict:
    """Run (seed, dist, policy) once with snapshot callbacks every `interval` seconds."""
    cfg = make_config(overrides)
    te = cfg.t_end(dist)
    scn = build_scenario(cfg, seed, dist)
    sim = Simulation(scn, make_policy(policy), cutoffs=[te])
    created = scn.created.tolist()
    frames = []
    t0 = cfg.dist_start - 60.0 if t_from is None else t_from
    times = [float(x) for x in np.arange(max(0.0, t0), cfg.horizon + 1e-9, interval)]
    for t in times:
        sim.at(t + FRAME_EPS, _snapshot, sim, frames, t, te, created, probe)
    sim.run()

    # blocks: mined time, miner, height, and whether they ended on the final best chain
    best, _ = sim.best_tip()
    on_best = set()
    b = sim.blocks[best]
    while b.id != 0:
        on_best.add(b.id)
        b = sim.blocks[b.parent]
    blocks = [dict(t=float(b.time), id=b.id, miner=b.miner, height=b.height, n_tx=len(b.txs),
                   stale=b.id not in on_best) for b in sim.blocks[1:]]
    d = scn.disturbance
    edges = list(scn.edges)
    series = dict(t=np.asarray(sim.series["t"], float), residue=np.asarray(sim.series[f"res@{te:g}"], float))
    if cfg.mempool_cap is not None:
        series["evdiv"] = np.asarray(sim.series[f"evdiv@{te:g}"], float)
    return dict(
        seed=int(seed), dist=dist, policy=policy, overrides=list(overrides), exploratory=bool(overrides),
        t_end=te, dist_start=cfg.dist_start, horizon=cfg.horizon, interval=float(interval),
        mempool_cap=cfg.mempool_cap, topology=cfg.topology,
        n=sim.n, edges=edges, positions=layout_positions(edges, sim.n),
        disturbance=dict(kind=d.kind, start=d.start, end=d.end, group_a=list(d.group_a), nodes=list(d.nodes)),
        affected=sorted(set(d.group_a) | set(d.nodes)),
        frames=frames,
        link_states=[[link_state(cfg, scn, a, bb, f["t"]) for a, bb in edges] for f in frames],
        blocks=blocks,
        policy_log=[(float(t), str(m)) for t, m in sim.policy.log],
        monitor_log=[(float(t), ev, int(a), int(bb)) for t, ev, a, bb in sim.monitor_log],
        timeline=[(float(t), s) for t, s in sim.policy.timeline],
        residue_series=series,
    )


@_cache
def replay(seed: int, dist: str, policy: str, overrides: tuple = (), interval: float = 5.0) -> dict:
    return compute_replay(seed, dist, policy, overrides, interval)


def events_between(rp: dict, t0: float, t1: float) -> list:
    """Block, reorg, policy and monitor events with t0 < t <= t1, as (time, kind, text), time-sorted."""
    out = []
    for b in rp["blocks"]:
        if t0 < b["t"] <= t1:
            out.append((b["t"], "block", f"block {b['id']} (height {b['height']}) mined by node {b['miner']}, "
                                         f"{b['n_tx']} tx" + ("; later left the best chain" if b["stale"] else "")))
    for t, msg in rp["policy_log"]:
        if t0 < t <= t1:
            out.append((t, "policy", msg))
    for t, ev, a, b in rp["monitor_log"]:
        if t0 < t <= t1:
            text = {"edge_down": f"monitor flags link {a}-{b} unhealthy", "edge_up": f"monitor sees link {a}-{b} healthy",
                    "alarm": "monitor raises the connectivity alarm",
                    "recovered": "monitor: every link healthy again"}[ev]
            out.append((t, "monitor", text))
    # reorgs (and, with a cap, evictions) only exist as counters; attribute them to the frame interval
    prev = None
    for f in rp["frames"]:
        if prev is not None and t0 < f["t"] <= t1:
            if f["reorgs"] > prev["reorgs"]:
                out.append((f["t"], "reorg", f"{f['reorgs'] - prev['reorgs']} reorg(s) since t={prev['t']:.0f} s; "
                                             f"{f['reorg_returned'] - prev['reorg_returned']} tx returned to mempools"))
            if "evicted" in f:
                for i, (e, r) in enumerate(zip(f["evicted"], f["rejected"])):
                    de, dr = e - prev["evicted"][i], r - prev["rejected"][i]
                    if de or dr:
                        out.append((f["t"], "eviction", f"node {i}: {de} tx evicted, {dr} rejected since "
                                                         f"t={prev['t']:.0f} s (minimum fee {f['min_fee'][i]:.2f})"))
        prev = f
    return sorted(out, key=lambda e: e[0])
