"""Everything that is fixed by the seed before a run starts (common random numbers).

For a given seed, every policy and both histories (clean / disturbed) receive the
same topology, link latencies, transaction workload, mining schedule and
disturbance targets. Only the disturbance itself (and, for the burst type, the
extra burst transactions) differs between a clean and a disturbed run, so any
difference in outcome is attributable to the disturbance's history.

The peer graph is a connected random regular graph (main study). Extension B adds
cfg.topology = "erdos_renyi" or "watts_strogatz"; the default draw is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from .config import DISTURBANCES, SimConfig

MASK64 = (1 << 64) - 1
INV53 = 1.0 / (1 << 53)


def u01(key: tuple) -> float:
    """Deterministic uniform(0,1) from an integer tuple (splitmix64 finaliser on the tuple hash).

    Tuple-of-int hashing is not salted by PYTHONHASHSEED, so draws are reproducible
    across processes. Keying draws by (seed, kind, message identity, link) gives the
    same network luck to the same message in every run of a seed.
    """
    z = hash(key) & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    z ^= z >> 31
    return ((z >> 11) + 0.5) * INV53


@dataclass
class Disturbance:
    kind: str | None
    start: float
    end: float
    group_a: tuple = ()          # partition: minority side
    nodes: tuple = ()            # isolation / loss / latency / asymmetric: affected nodes


@dataclass
class Scenario:
    seed: int
    cfg: SimConfig
    edges: list
    peers: list
    lat: list                    # lat[a][b] one-way latency (s), symmetric
    created: np.ndarray          # creation time per tx id
    origin: np.ndarray
    fee: np.ndarray
    is_base: np.ndarray          # True for the shared workload, False for burst extras
    n_base: int
    block_times: np.ndarray
    block_miners: np.ndarray
    disturbance: Disturbance
    t_end: float
    extra: dict = field(default_factory=dict)


def _graph(cfg: SimConfig, gseed: int):
    """One draw of the peer graph. 'random_regular' is the main study; the others are Extension B."""
    if cfg.topology == "random_regular":
        return nx.random_regular_graph(cfg.degree, cfg.n_nodes, seed=gseed)
    if cfg.topology == "erdos_renyi":          # G(n, p) with expected degree `degree`
        return nx.gnp_random_graph(cfg.n_nodes, min(1.0, cfg.degree / (cfg.n_nodes - 1)), seed=gseed)
    if cfg.topology == "watts_strogatz":       # ring lattice with `degree` neighbours, rewired with ws_rewire
        return nx.watts_strogatz_graph(cfg.n_nodes, cfg.degree, cfg.ws_rewire, seed=gseed)
    raise ValueError(f"unknown topology {cfg.topology!r}")


def _topology(cfg: SimConfig, seed: int):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    for attempt in range(1000):
        g = _graph(cfg, int(rng.integers(1 << 31)))
        if nx.is_connected(g):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not build a connected topology")
    n = cfg.n_nodes
    lat = [[0.0] * n for _ in range(n)]
    edges = sorted((min(a, b), max(a, b)) for a, b in g.edges())
    for a, b in edges:
        lat[a][b] = lat[b][a] = float(rng.uniform(cfg.lat_min, cfg.lat_max))
    peers = [sorted(g.neighbors(i)) for i in range(n)]
    return edges, peers, lat


def _workload(cfg: SimConfig, seed: int, with_burst: bool):
    ss_base, ss_burst, ss_blk = np.random.SeedSequence([seed, 2]).spawn(3)
    rng = np.random.default_rng(ss_base)
    n_guess = int(cfg.tx_rate * cfg.horizon * 1.5) + 200
    times = np.cumsum(rng.exponential(1.0 / cfg.tx_rate, n_guess))
    assert times[-1] > cfg.horizon
    times = times[times < cfg.horizon]
    n = len(times)
    origin = rng.integers(0, cfg.n_nodes, n_guess)[:n]
    fee = rng.lognormal(0.0, cfg.fee_sigma, n_guess)[:n]

    # burst extras come from their own stream so the base workload is byte-identical
    rngb = np.random.default_rng(ss_burst)
    b0, b1 = cfg.dist_start, cfg.dist_start + cfg.burst_duration
    extra_rate = cfg.tx_rate * (cfg.burst_factor - 1.0)
    m_guess = int(extra_rate * cfg.burst_duration * 2) + 50
    bt = b0 + np.cumsum(rngb.exponential(1.0 / extra_rate, m_guess))
    bt = bt[bt < b1]
    m = len(bt)
    borigin = rngb.integers(0, cfg.n_nodes, m_guess)[:m]
    bfee = rngb.lognormal(0.0, cfg.fee_sigma, m_guess)[:m]

    if with_burst:
        created = np.concatenate([times, bt])
        orig = np.concatenate([origin, borigin])
        fees = np.concatenate([fee, bfee])
        is_base = np.concatenate([np.ones(n, bool), np.zeros(m, bool)])
    else:
        created, orig, fees, is_base = times, origin, fee, np.ones(n, bool)

    rngk = np.random.default_rng(ss_blk)
    k_guess = int(cfg.horizon / cfg.block_interval * 2) + 50
    btimes = np.cumsum(rngk.exponential(cfg.block_interval, k_guess))
    btimes = btimes[btimes < cfg.horizon]
    miners = rngk.integers(0, cfg.n_nodes, k_guess)[: len(btimes)]
    return created, orig, fees, is_base, n, btimes, miners


def _disturbance(cfg: SimConfig, seed: int, kind: str | None) -> Disturbance:
    if kind is None:
        return Disturbance(None, cfg.dist_start, cfg.dist_start)
    idx = DISTURBANCES.index(kind)
    rng = np.random.default_rng(np.random.SeedSequence([seed, 3, idx]))
    n = cfg.n_nodes
    start = cfg.dist_start
    end = cfg.t_end(kind)
    frac = rng.uniform(cfg.affected_frac_min, cfg.affected_frac_max)
    k = int(np.clip(round(frac * n), 1, n - 1))
    perm = [int(x) for x in rng.permutation(n)]
    if kind == "partition":
        return Disturbance(kind, start, end, group_a=tuple(sorted(perm[:k])))
    if kind == "isolation":
        return Disturbance(kind, start, end, nodes=tuple(sorted(perm[: cfg.isolation_k])))
    if kind in ("loss", "latency", "asymmetric"):
        return Disturbance(kind, start, end, nodes=tuple(sorted(perm[:k])))
    if kind == "burst":
        return Disturbance(kind, start, end)
    raise ValueError(kind)


def build_scenario(cfg: SimConfig, seed: int, dist: str | None, t_end: float | None = None) -> Scenario:
    edges, peers, lat = _topology(cfg, seed)
    created, origin, fee, is_base, n_base, btimes, miners = _workload(cfg, seed, dist == "burst")
    d = _disturbance(cfg, seed, dist)
    te = t_end if t_end is not None else cfg.t_end(dist)
    return Scenario(seed, cfg, edges, peers, lat, created, origin, fee, is_base, n_base,
                    btimes, miners, d, te)
