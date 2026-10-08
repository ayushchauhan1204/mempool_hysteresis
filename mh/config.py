"""All simulation parameters in one frozen dataclass.

Every number used by the simulator, the policies and the evaluator lives here so
that a run is fully described by (SimConfig, seed, disturbance type, policy).
Calibrated values (tau_m, eps_D, beta, eps_size) are overwritten in Phase 3 from
clean dev-seed runs; the defaults below are placeholders, not results.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

DISTURBANCES = ("partition", "isolation", "loss", "latency", "asymmetric", "burst")
POLICIES = ("B1", "B2", "SARA", "SARA-D", "SARA-R", "SARA-V")


@dataclass(frozen=True)
class SimConfig:
    # ---------------- network ----------------
    n_nodes: int = 10
    degree: int = 4
    lat_min: float = 0.020          # one-way link latency lower bound (s)
    lat_max: float = 0.120          # one-way link latency upper bound (s)
    tx_hop_factor: float = 3.0      # inv -> getdata -> tx: three one-way trips per hop
    trickle_mean: float = 1.0       # mean relay batching delay per hop (s), exponential
    block_hop_factor: float = 2.0   # announce + fetch
    block_validation: float = 0.05  # per-hop block validation time (s)
    bandwidth: float = 1.25e6       # bytes/s per link (10 Mbit/s)
    tx_bytes: int = 250
    reconnect_max: float = 2.0      # reconnection after an outage ends ~ U(0, reconnect_max) s
    transport: str = "tcp"          # "tcp": loss -> retransmission delay; "lossy": loss -> message dropped
    outage_mode: str = "reset"      # "reset": partition/isolation drop connections; "buffered": they survive
    rto_min: float = 0.2            # minimum TCP retransmission timeout (s)
    rto_max_k: int = 9              # cap on consecutive retransmissions
    buffer_flush_cap: float = 64.0  # cap on residual backoff when a blackholed TCP link heals (s)

    # ---------------- workload ----------------
    tx_rate: float = 4.0            # transactions per second (Poisson)
    fee_sigma: float = 1.0          # fee rate ~ lognormal(0, fee_sigma)

    # ---------------- blocks ----------------
    block_interval: float = 15.0    # mean seconds between blocks (Poisson, network-wide)
    block_capacity: int = 80        # transactions per block
    relay_reorged: bool = False     # re-announce transactions returned to the mempool by a reorg

    # ---------------- timeline ----------------
    dist_start: float = 300.0
    dist_duration: float = 60.0
    burst_duration: float = 30.0
    horizon: float = 960.0

    # ---------------- disturbance severities ----------------
    loss_p: float = 0.5
    latency_mult: float = 40.0
    burst_factor: float = 6.0
    affected_frac_min: float = 0.3
    affected_frac_max: float = 0.5
    isolation_k: int = 1

    # ---------------- connectivity monitor (shared by all policies) ----------------
    ping_interval: float = 1.0
    ping_timeout: float = 5.0
    ping_window: int = 5
    ping_fail_threshold: int = 2
    rtt_slow_factor: float = 3.0
    healthy_streak: int = 5

    # ---------------- SARA ----------------
    audit_interval: float = 2.0
    tau_m: float = 15.0             # maturity: ignore transactions younger than this (calibrated)
    eps_D: float = 0.02             # control limit for divergence D (calibrated)
    beta: float = 3.0               # control limit for backlog B, in blocks (calibrated)
    eps_size: float = 0.25          # control limit for the -D size proxy (calibrated)
    verify_window: int = 5          # consecutive LOW audits required to confirm recovery
    persist_escalation: int = 5     # consecutive exceedances that raise the tier by one
    open_debounce: int = 2          # consecutive exceedances before a state-based incident/action
    pull_retry: float = 5.0         # do not re-request a (node, tx) pull within this many seconds

    # ---------------- evaluation ----------------
    eval_interval: float = 1.0
    eval_start: float = 240.0
    hold_window: float = 10.0       # truth must hold this long to count as recovered (s)
    post_workload_window: float = 300.0
    residue_window: float = 600.0

    # ---------------- extensions (results/extensions/); every one is off by default ----------------
    topology: str = "random_regular"   # B: "random_regular" (main study), "erdos_renyi", "watts_strogatz"
    ws_rewire: float = 0.1             # B: Watts-Strogatz rewiring probability
    mempool_cap: int | None = None     # C: max pending transactions per node; None = unlimited (main study)

    def with_(self, **kw) -> "SimConfig":
        return replace(self, **kw)

    def as_dict(self) -> dict:
        return asdict(self)

    def t_end(self, dist: str | None) -> float:
        """Time the disturbance ends; for a clean run use the paired disturbed run's value."""
        if dist == "burst":
            return self.dist_start + self.burst_duration
        return self.dist_start + self.dist_duration
