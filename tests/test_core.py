"""Unit tests for the pieces whose correctness every result depends on (plan Phase 2)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mh.config import SimConfig  # noqa: E402
from mh.metrics import first_hold, recovered_measure  # noqa: E402
from mh.policies import CRITICAL, HIGH, LOW, MODERATE, make_policy, risk_tier  # noqa: E402
from mh.scenario import build_scenario, u01  # noqa: E402
from mh.sim import Block, Simulation, pairwise_jaccard, residue_set  # noqa: E402


def test_u01_deterministic_and_uniform():
    a = [u01((1, 2, i, 3, 4)) for i in range(50000)]
    assert a[:10] == [u01((1, 2, i, 3, 4)) for i in range(10)]
    assert 0.0 < min(a) and max(a) < 1.0
    assert abs(np.mean(a) - 0.5) < 0.01
    assert abs(np.corrcoef(a[:-1], a[1:])[0, 1]) < 0.02


def test_pairwise_jaccard_hand_example():
    # R = {1,2,3,4}; A knows all, B lacks 3, C lacks 2
    # D(A,B)=1-3/4, D(A,C)=1-3/4, D(B,C)=1-2/4 -> mean 1/3
    assert pairwise_jaccard([set(), {3}, {2}], 4) == pytest.approx(1 / 3)
    assert pairwise_jaccard([set(), set(), set()], 4) == 0.0
    assert pairwise_jaccard([set(), set()], 0) == 0.0


def test_residue_set_definition():
    created = [0.0, 0.0, 0.0, 0.0, 100.0]
    mps = [{0: 0, 1: 0, 4: 100}, {1: 0}, {}]
    confs = [{2}, {2, 0}, {2}]
    union = set().union(*[m.keys() for m in mps])
    # tx0: pending at n0, confirmed at n1, unknown at n2 -> residue
    # tx1: pending at n0,n1, unknown at n2 -> residue
    # tx4: created after the cutoff -> excluded; tx2: pending nowhere -> excluded
    assert residue_set(union, mps, confs, created, 50.0) == {0, 1}
    mps2 = [{0: 0, 1: 0}, {1: 0}, {1: 0}]
    confs2 = [{2}, {2, 0}, {2, 0}]
    assert residue_set(set().union(*[m.keys() for m in mps2]), mps2, confs2, created, 50.0) == set()


def _tiny_sim():
    cfg = SimConfig(n_nodes=4, degree=2)
    scn = build_scenario(cfg, 0, None)
    return Simulation(scn, make_policy("B1"))


def test_reorg_returns_transactions_and_confirms_new_branch():
    sim = _tiny_sim()
    sim.mempool[0] = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    sim.seen[0] = dict(sim.mempool[0])
    sim.blocks += [Block(1, 0, 1, 0, (0, 1), 1.0), Block(2, 0, 1, 1, (1, 2), 1.0),
                   Block(3, 2, 2, 1, (3,), 2.0)]
    sim._recv_block(0, 1, -1)
    assert sim.tip[0] == 1 and sim.conf[0] == {0, 1} and set(sim.mempool[0]) == {2, 3}
    sim._recv_block(0, 2, -1)          # same height: stay on the first-seen tip
    assert sim.tip[0] == 1
    sim._recv_block(0, 3, -1)          # longer branch: reorg
    assert sim.tip[0] == 3 and sim.chain[0] == [0, 2, 3]
    assert sim.conf[0] == {1, 2, 3}
    assert set(sim.mempool[0]) == {0}  # tx0 returned to the mempool; tx1 re-confirmed
    assert sim.c["reorg_returned"] == 1


def test_orphan_block_waits_for_parent():
    sim = _tiny_sim()
    sim.blocks += [Block(1, 0, 1, 0, (5,), 1.0), Block(2, 1, 2, 0, (6,), 2.0)]
    sim._recv_block(1, 2, -1)          # parent unknown -> orphan
    assert sim.tip[1] == 0 and 2 not in sim.known[1]
    sim._recv_block(1, 1, -1)
    assert sim.tip[1] == 2 and sim.conf[1] == {5, 6}


def test_risk_tiers():
    cfg = SimConfig()  # debounce 2, persistence escalation 5
    assert risk_tier(0.5, 0, 0, 10, cfg) == (LOW, LOW)
    assert risk_tier(1.5, 1, 1, 10, cfg) == (MODERATE, LOW)        # debounced
    assert risk_tier(1.5, 2, 1, 10, cfg) == (MODERATE, MODERATE)
    assert risk_tier(3.0, 2, 1, 10, cfg) == (HIGH, HIGH)
    assert risk_tier(5.0, 2, 1, 10, cfg) == (CRITICAL, CRITICAL)
    assert risk_tier(1.5, 5, 1, 10, cfg) == (MODERATE, HIGH)       # persistence escalation
    assert risk_tier(1.5, 2, 5, 10, cfg) == (MODERATE, HIGH)       # half the nodes affected


def test_first_hold_and_recovered_measure():
    t = np.arange(0, 21, 1.0)
    ok = np.array([False] * 5 + [True] * 5 + [False] + [True] * 10)
    assert first_hold(t, ok, 0.0, 5.0) == (11.0, False)
    assert first_hold(t, ok, 0.0, 4.0) == (5.0, False)
    tt, cens = first_hold(t, np.zeros(21, bool), 0.0, 5.0)
    assert cens
    tl = [(0.0, "recovered"), (10.0, "incident"), (20.0, "recovered")]
    assert recovered_measure(tl, 5.0, 25.0) == pytest.approx(10.0)
    assert recovered_measure(tl, 12.0, 18.0) == 0.0


def test_common_random_numbers_shared_across_histories():
    cfg = SimConfig()
    clean = build_scenario(cfg, 7, None)
    burst = build_scenario(cfg, 7, "burst")
    part = build_scenario(cfg, 7, "partition")
    n = clean.n_base
    assert np.array_equal(clean.created, burst.created[:n])
    assert np.array_equal(clean.origin, part.origin)
    assert np.array_equal(clean.block_times, burst.block_times)
    assert np.array_equal(clean.block_miners, part.block_miners)
    assert clean.edges == part.edges
    assert len(burst.created) > n


def test_state_invariants_after_partition():
    from experiments.sanity import invariants
    cfg = SimConfig()
    scn = build_scenario(cfg, 0, "partition")
    sim = Simulation(scn, make_policy("SARA")).run()
    assert invariants(sim) == 0
