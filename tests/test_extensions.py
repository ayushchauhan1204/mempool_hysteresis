"""Unit tests for the extension features (all off by default; see results/extensions/EXTENSIONS.md)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mh.config import SimConfig  # noqa: E402
from mh.ext_metrics import (best_chain, block_composition, confirmation_times, delay_summary,  # noqa: E402
                            excess_summary, window_ids)
from mh.policies import make_policy  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402
from mh.sim import Block, Simulation  # noqa: E402


def _tiny_sim(**kw):
    cfg = SimConfig(n_nodes=4, degree=2, **kw)
    scn = build_scenario(cfg, 0, None)
    return Simulation(scn, make_policy("B1"))


# ------------------------------------------------------------------------------ Extension A
def test_confirmation_delay_hand_built_chain():
    sim = _tiny_sim()
    # best chain 0 <- 1 (t=10: tx0, tx1) <- 2 (t=25: tx2); block 3 (t=12: tx3) is a stale fork at height 1
    sim.blocks += [Block(1, 0, 1, 0, (0, 1), 10.0), Block(2, 1, 2, 1, (2,), 25.0), Block(3, 0, 1, 2, (3,), 12.0)]
    sim.tip = [2, 2, 3, 2]
    conf = confirmation_times(sim)
    assert [b.id for b in best_chain(sim)] == [1, 2]
    assert conf[0] == 10.0 and conf[1] == 10.0 and conf[2] == 25.0
    assert math.isnan(conf[3]) and np.isnan(conf[4:]).all()

    created = np.array([1.0, 4.0, 20.0, 5.0])
    s = delay_summary(created, conf[:4], np.arange(4), horizon=960.0)
    assert s["n"] == 4 and s["never"] == 1
    assert s["mean"] == pytest.approx((9 + 6 + 5) / 3)
    assert s["median"] == pytest.approx(6.0)
    assert s["mean_cens"] == pytest.approx((9 + 6 + 5 + 955) / 4)     # tx3 censored at 960 - 5

    # clean history: tx1 at 30, tx3 at 15 -> excess per tx: 0, -20, 0, 955 - 10
    conf_c = np.array([10.0, 30.0, 25.0, 15.0])
    x = excess_summary(created, conf[:4], conf_c, np.arange(4), horizon=960.0)
    assert x["mean"] == pytest.approx((0 - 20 + 0 + 945) / 4)
    assert x["never_extra"] == 1
    assert x["share_delayed"] == pytest.approx(0.25)

    # block composition in [10, 30): disturbed {0, 1, 2}; clean blocks hold {0, 2, 3}
    chain_c = [Block(1, 0, 1, 0, (0, 3), 10.0), Block(2, 1, 2, 1, (2,), 25.0)]
    bc = block_composition(best_chain(sim), chain_c, 10.0, 30.0, np.ones(4, bool))
    assert bc["bcd"] == pytest.approx(1 - 2 / 4)
    assert bc["displaced"] == 1 and bc["added"] == 1 and bc["blocks_d"] == 2 and bc["blocks_c"] == 2


def test_window_ids_shared_workload_only():
    created = np.array([0.0, 10.0, 20.0, 30.0, 15.0])
    is_base = np.array([True, True, True, True, False])
    assert window_ids(created, is_base, 10.0, 30.0).tolist() == [1, 2]


# ------------------------------------------------------------------------------ Extension B
def _graph_of(scn):
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(scn.cfg.n_nodes))
    g.add_edges_from(scn.edges)
    return g


@pytest.mark.parametrize("n,d", [(10, 4), (10, 8), (20, 4), (20, 8), (50, 4), (50, 8)])
def test_topologies_connected_with_requested_size_and_degree(n, d):
    import networkx as nx
    mean_er = []
    for seed in range(3000, 3010):
        for topo in ("random_regular", "erdos_renyi", "watts_strogatz"):
            scn = build_scenario(SimConfig(n_nodes=n, degree=d, topology=topo), seed, None)
            g = _graph_of(scn)
            assert g.number_of_nodes() == n and nx.is_connected(g), (topo, seed)
            degs = [len(p) for p in scn.peers]
            assert degs == [g.degree(i) for i in range(n)]
            # links are symmetric and every edge has a latency in range
            for a, b in scn.edges:
                assert scn.lat[a][b] == scn.lat[b][a] and 0.02 <= scn.lat[a][b] <= 0.12
            if topo == "random_regular":
                assert set(degs) == {d}
            elif topo == "watts_strogatz":            # rewiring keeps the edge count of the k-ring lattice
                assert g.number_of_edges() == n * d // 2
            else:
                mean_er.append(np.mean(degs))
    # Erdos-Renyi: expected degree `d` (conditioning on connectivity nudges it up slightly)
    assert abs(np.mean(mean_er) - d) < 0.25 * d


def test_default_topology_is_the_main_study_graph():
    a = build_scenario(SimConfig(), 1000, "partition")
    b = build_scenario(SimConfig(topology="random_regular"), 1000, "partition")
    assert a.edges == b.edges and a.lat == b.lat
    assert build_scenario(SimConfig(topology="erdos_renyi"), 1000, "partition").edges != a.edges
    with pytest.raises(ValueError):
        build_scenario(SimConfig(topology="ring"), 1000, None)


# ------------------------------------------------------------------------------ Extension C
def _capped_sim(cap, policy="B1"):
    cfg = SimConfig(n_nodes=4, degree=2, mempool_cap=cap)
    scn = build_scenario(cfg, 0, None)
    sim = Simulation(scn, make_policy(policy))
    sim.fee = [1.0, 2.0, 3.0, 0.5, 2.5, 0.8, 0.9, 1.5, 5.0, 6.0, 0.1, 0.2] + [1.0] * (len(sim.fee) - 12)
    return sim


def test_eviction_order_and_rejection():
    sim = _capped_sim(3)
    for x in (0, 1, 2):                                   # fees 1.0, 2.0, 3.0 fill the mempool
        assert sim._accept_tx(0, x, -1)
    assert not sim._accept_tx(0, 3, -1)                   # fee 0.5 below every fee held: rejected
    assert sim.dropped[0][3][1] == "rejected" and sim.min_fee[0] == 0.5 and 3 in sim.seen[0]
    assert sim._accept_tx(0, 4, -1)                       # fee 2.5 evicts the lowest (tx0, fee 1.0)
    assert set(sim.mempool[0]) == {1, 2, 4} and sim.dropped[0][0][1] == "evicted" and sim.min_fee[0] == 1.0
    del sim.mempool[0][2]                                 # tx2 confirmed elsewhere: there is room again
    sim.conf[0].add(2)
    assert not sim._accept_tx(0, 6, -1)                   # fee 0.9 < rolling minimum 1.0 although not full
    assert sim._accept_tx(0, 7, -1)                       # fee 1.5 >= minimum and room: accepted
    assert not sim._accept_tx(0, 0, -1)                   # recently-rejected memory: evicted tx0 ignored
    assert sim.c["evicted"] == 1 and sim.c["rejected"] == 2
    assert sim.mempool[1] == {} and sim.min_fee[1] == 0.0  # other nodes untouched


def test_evicted_tx_is_not_served_and_a_delivery_is_refused():
    sim = _capped_sim(3, policy="SARA")
    for x in (0, 1, 2, 4):                                # tx4 evicts tx0 at node 0
        sim._accept_tx(0, x, -1)
    sent = []
    sim._send = lambda a, b, delay, kind, ident, fn, args: sent.append(args)
    sim._serve_txs(0, 1, [0, 1, 4], sim.policy.ctr, None)
    assert sent[-1][2] == [1, 4]                          # tx0 was evicted: cannot be served
    sim._recv_txs(1, 0, [0], sim.policy.ctr, None)        # a pull re-delivers tx0 to node 0
    assert 0 not in sim.mempool[0] and sim.c["refused_deliveries"] == 1
    assert (0, 0) in sim.policy.unrepairable and sim.policy.ctr["unrepairable"] == 1
    sim._recv_txs(1, 0, [3], sim.policy.ctr, None)        # new tx below every fee held, mempool full
    assert (0, 3) in sim.policy.unrepairable and sim.c["refused_deliveries"] == 2


def test_reorg_returns_are_trimmed_to_the_cap():
    sim = _capped_sim(2)
    sim._accept_tx(0, 8, -1)                              # fee 5.0
    sim._accept_tx(0, 9, -1)                              # fee 6.0
    sim.blocks += [Block(1, 0, 1, 0, (8, 9), 1.0), Block(2, 0, 1, 1, (), 1.0), Block(3, 2, 2, 1, (), 2.0)]
    sim._recv_block(0, 1, -1)                             # tx8, tx9 confirmed
    assert sim.mempool[0] == {}
    sim._accept_tx(0, 10, -1)                             # fee 0.1
    sim._accept_tx(0, 11, -1)                             # fee 0.2 -> mempool full again
    sim._recv_block(0, 2, -1)
    sim._recv_block(0, 3, -1)                             # reorg: tx8, tx9 return, cap 2 keeps the best two
    assert set(sim.mempool[0]) == {8, 9}
    assert sim.dropped[0][10][1] == "evicted" and sim.dropped[0][11][1] == "evicted"
    assert sim.min_fee[0] == 0.2


def test_no_eviction_when_cap_is_off():
    sim = _tiny_sim()
    for x in range(200):
        assert sim._accept_tx(0, x, -1)
    assert len(sim.mempool[0]) == 200
    assert sim.cap is None and not hasattr(sim, "dropped") and "evicted" not in sim.c


def test_cap_that_never_binds_changes_nothing():
    from mh.runner import run_one
    base = SimConfig()
    for dist, pol in (("partition", "SARA"), (None, "B1")):
        a = run_one(base, 0, dist, pol, cutoffs=[360.0])
        b = run_one(base.with_(mempool_cap=10 ** 9), 0, dist, pol, cutoffs=[360.0])
        assert b["counters"]["evicted"] == 0 and b["counters"]["rejected"] == 0
        for k, v in a["metrics"]["360"].items():
            assert (v == b["metrics"]["360"][k]) or (v != v and b["metrics"]["360"][k] != b["metrics"]["360"][k]), k
        for k, v in a["series"].items():
            assert np.array_equal(v, b["series"][k], equal_nan=v.dtype.kind == "f"), k
        assert np.nansum(b["series"]["evdiv@360"]) == 0 and b["series"]["lost"].max() == 0
        if dist is None:                                  # clean history: zero residue and evicted-divergence
            assert np.nansum(b["series"]["res@360"]) == 0 and np.nansum(b["series"]["gres@360"]) == 0
