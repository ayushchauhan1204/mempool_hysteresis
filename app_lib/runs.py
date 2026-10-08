"""Live simulation runs for the frontend.

* Config: the calibrated SimConfig from mh.calibration.load_config(). Every override is applied to a copy
  (SimConfig is frozen; ``with_`` returns a new object) and never written back. A run that changes any study
  setting is labelled "exploratory, not part of the study".
* Runs: thin wrappers around mh.runner.run_one, called exactly as demo.py calls it (the clean B1 history first;
  its pending-set series is the backlog counterfactual for every policy). Cached with st.cache_data on
  (seed, disturbance, policy, normalised overrides).
* Extension metrics from mh.ext_metrics: confirmation delay and excess delay against the paired clean history
  (Extension A) and, when a mempool cap is set, evicted-divergence and eviction counts (Extension C).
* Verdicts: one-line plain-language summaries generated from the metrics dict, never hand-typed.
"""
from __future__ import annotations

import math
import sys
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import demo  # noqa: E402  (describe/fmt reused so the app shows exactly what demo.py prints)
from mh.calibration import load_config  # noqa: E402
from mh.config import DISTURBANCES, POLICIES, SimConfig  # noqa: E402
from mh.ext_metrics import (best_chain, block_composition, capacity_metrics, confirmation_times,  # noqa: E402
                            delay_summary, excess_summary, window_ids, windows)
from mh.runner import run_one  # noqa: E402

try:
    import streamlit as st
    _cache = st.cache_data(max_entries=256, show_spinner=False)
except ImportError:  # pragma: no cover - the app needs streamlit; the tests use the uncached functions
    import functools
    _cache = functools.lru_cache(maxsize=256)

COMPARE_POLICIES = tuple(demo.POLS)          # ("B1", "B2", "SARA"), as in demo.py
DIST_LABEL = dict(partition="Partition", isolation="Node isolation", loss="Packet loss",
                  latency="Latency spike", asymmetric="Asymmetric link", burst="Transaction burst")
POLICY_LABEL = {"B1": "B1 connectivity-only", "B2": "B2 protocol resync", "SARA": "SARA",
                "SARA-D": "SARA −D (size proxy)", "SARA-R": "SARA −R (no risk tiers)",
                "SARA-V": "SARA −V (no verification)"}
TOPOLOGY_LABEL = {"random_regular": "Random regular (study)", "erdos_renyi": "Erdős–Rényi",
                  "watts_strogatz": "Watts–Strogatz"}
EXPLORATORY = "Exploratory, not part of the study"
DEFAULT_SEED = 1000
MAX_NODES = 50          # Extension B: one 100-node run took several minutes, so 50 is the largest size offered
SLOW_NODES = 20         # above this a run takes noticeably longer (Extension B timings)

# Disturbance parameters: each affects only its own disturbance type.
DIST_PARAMS = {
    "loss_p": dict(label="Loss probability", dists=("loss",), min=0.05, max=0.95, step=0.05, kind=float),
    "latency_mult": dict(label="Latency multiplier", dists=("latency",), min=1.0, max=100.0, step=1.0, kind=float),
    "burst_factor": dict(label="Burst factor (× arrival rate)", dists=("burst",), min=1.5, max=20.0, step=0.5,
                         kind=float),
    "dist_duration": dict(label="Disturbance duration (s)",
                          dists=("partition", "isolation", "loss", "latency", "asymmetric"),
                          min=10.0, max=240.0, step=5.0, kind=float),
    "burst_duration": dict(label="Burst duration (s)", dists=("burst",), min=10.0, max=120.0, step=5.0, kind=float),
}
# Model parameters (Extensions B and C): each affects every run.
MODEL_PARAMS = {
    "topology": dict(label="Topology", choices=tuple(TOPOLOGY_LABEL), kind=str),
    "n_nodes": dict(label="Nodes", min=4, max=MAX_NODES, step=1, kind=int),
    "degree": dict(label="Degree (expected degree for Erdős–Rényi)", min=2, max=12, step=1, kind=int),
    "tx_rate": dict(label="Transaction rate (tx/s)", min=0.5, max=20.0, step=0.5, kind=float),
    "block_capacity": dict(label="Block capacity (tx)", min=10, max=2000, step=10, kind=int),
    "mempool_cap": dict(label="Mempool capacity (tx per node)", min=20, max=10000, step=10, kind=int),
}
OVERRIDABLE = {**DIST_PARAMS, **MODEL_PARAMS}
ChainBlock = namedtuple("ChainBlock", "time txs")


def base_config() -> SimConfig:
    """The calibrated configuration (dev-seed calibration applied). Never modified."""
    return load_config()


def seed_note(seed: int) -> str:
    if 0 <= seed <= 4:
        return "Seeds 0–4 were used for calibration, so results on them are not independent."
    if 1000 <= seed <= 1199:
        return "Held-out study seed (1000–1199): with study settings this run is one of the 200 seeds in the study."
    if 2000 <= seed <= 2049:
        return "Robustness-sweep seed (2000–2049)."
    if 3000 <= seed <= 3099:
        return "Extension seed (3000–3099)."
    return "Seed outside the study ranges; seeds 0–4 were used for calibration and are not independent."


def scaled_capacity(tx_rate: float, base: SimConfig | None = None) -> int:
    """Block capacity that keeps block-space utilisation at the calibrated value (as Extension B does)."""
    base = base or base_config()
    return int(round(base.block_capacity * tx_rate / base.tx_rate))


# ----------------------------------------------------------------------------- overrides
def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return b is not None and a is not None and math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
    return a == b


def validate_graph(topology: str, n: int, d: int) -> str | None:
    """None if the topology can be drawn with n nodes and degree d, else the reason."""
    if not 1 <= d < n:
        return f"degree {d} must be between 1 and {n - 1} for {n} nodes"
    if topology == "random_regular" and (n * d) % 2:
        return "a random regular graph needs nodes × degree to be even"
    if topology == "watts_strogatz" and d % 2:
        return "Watts–Strogatz needs an even degree (k neighbours on the ring)"
    return None


def normalize_overrides(dist: str, overrides: dict | None, base: SimConfig | None = None) -> tuple:
    """Cache-key form of the user's overrides for one disturbance: a sorted tuple of (name, value) containing only
    parameters that affect `dist` and differ from the calibrated study setting. Raises ValueError if invalid."""
    base = base or base_config()
    out = []
    for k, v in (overrides or {}).items():
        spec = OVERRIDABLE.get(k)
        if spec is None:
            raise ValueError(f"{k} is not an overridable parameter")
        if v is None or (k in DIST_PARAMS and dist not in spec["dists"]):
            continue                                 # None = study setting (mempool_cap: unlimited)
        if spec["kind"] is str:
            if v not in spec["choices"]:
                raise ValueError(f"{k}={v!r} is not one of {spec['choices']}")
        else:
            v = spec["kind"](v)
            if not spec["min"] <= v <= spec["max"]:
                raise ValueError(f"{spec['label']} {v} outside [{spec['min']}, {spec['max']}]")
        if _same(v, getattr(base, k)):
            continue
        out.append((k, v))
    o = dict(out)
    why = validate_graph(o.get("topology", base.topology), o.get("n_nodes", base.n_nodes), o.get("degree", base.degree))
    if why:
        raise ValueError(why)
    return tuple(sorted(out))


def ignored_overrides(dist: str, overrides: dict | None, base: SimConfig | None = None) -> list:
    """Disturbance parameters the user changed that do not affect `dist` (shown as a note)."""
    base = base or base_config()
    return [k for k, v in (overrides or {}).items()
            if k in DIST_PARAMS and v is not None and dist not in DIST_PARAMS[k]["dists"]
            and not _same(v, getattr(base, k))]


def make_config(overrides: tuple = (), base: SimConfig | None = None) -> SimConfig:
    """Copy of the calibrated config with `overrides` applied. A longer disturbance extends the horizon by the same
    amount so the post-disturbance observation window keeps its calibrated length."""
    base = base or base_config()
    if not overrides:
        return base
    cfg = base.with_(**dict(overrides))
    extra = max(cfg.dist_duration - base.dist_duration, cfg.burst_duration - base.burst_duration, 0.0)
    if extra > 0:
        cfg = cfg.with_(horizon=base.horizon + extra)
    return cfg


def run_key(seed: int, dist: str | None, policy: str, overrides: tuple = ()) -> tuple:
    return (int(seed), dist, policy, tuple(overrides))


def describe_overrides(overrides: tuple, cfg: SimConfig | None = None) -> str:
    base = base_config()
    parts = []
    for k, v in overrides:
        old, new = getattr(base, k), v
        if k == "topology":
            old, new = TOPOLOGY_LABEL[old], TOPOLOGY_LABEL[new]
        if k == "mempool_cap":
            old = "unlimited"
        parts.append(f"{OVERRIDABLE[k]['label']} {old:g} → {new:g}" if isinstance(new, float)
                     else f"{OVERRIDABLE[k]['label']} {old} → {new}")
    if cfg is not None and cfg.horizon != base.horizon:
        parts.append(f"horizon {base.horizon:g} → {cfg.horizon:g} s (keeps the post-disturbance window)")
    return "; ".join(parts)


# ----------------------------------------------------------------------------- runs (uncached)
def traffic_kB(m: dict) -> float:
    """In-band recovery traffic, same formula as demo.py and experiments/analyze.py (inband_kB)."""
    return (m["announced"] * 36 + m["requested"] * 36 + m["transfers"] * 250) / 1000


def compute_reference(seed: int, cutoff: float, overrides: tuple = ()) -> dict:
    """Clean (undisturbed) B1 history, as in demo.py: the backlog counterfactual and, for Extension A, the paired
    confirmation times and final-chain block contents."""
    cfg = make_config(overrides)
    r = run_one(cfg, seed, None, "B1", cutoffs=[cutoff], keep_log=True)
    sim = r.pop("sim")
    return dict(t=np.asarray(r["series"]["t"]), pend=np.asarray(r["series"]["pend"]),
                conf=confirmation_times(sim), chain=[ChainBlock(b.time, tuple(b.txs)) for b in best_chain(sim)],
                counters=dict(r["counters"]))


def extension_a(cfg: SimConfig, te: float, sim, ref: dict) -> dict:
    """Extension A metrics for one run, exactly as experiments/ext_a_confirmation.py computes them."""
    scn = sim.scn
    conf = confirmation_times(sim)
    out = {}
    for w, (lo, hi) in windows(cfg, te).items():
        ids = window_ids(scn.created, scn.is_base, lo, hi)
        out[w] = dict(window=(lo, hi), delay=delay_summary(scn.created, conf, ids, cfg.horizon),
                      excess=excess_summary(scn.created, conf, ref["conf"], ids, cfg.horizon))
    out["blocks"] = block_composition(best_chain(sim), ref["chain"], te, te + cfg.post_workload_window, scn.is_base)
    extra = np.nonzero(~scn.is_base)[0]
    out["burst_extra"] = dict(n=int(len(extra)), never=int(np.sum(~np.isfinite(conf[extra]))) if len(extra) else 0)
    lo, hi = windows(cfg, te)["exposed"]
    ids = window_ids(scn.created, scn.is_base, lo, hi)
    out["per_tx"] = dict(created=np.asarray(scn.created)[ids], delay=conf[ids] - np.asarray(scn.created)[ids],
                         clean_delay=np.asarray(ref["conf"])[ids] - np.asarray(scn.created)[ids])
    return out


def node_drops(sim) -> list | None:
    """Per node, with a mempool cap: transactions evicted and rejected, and the rolling minimum fee (read only)."""
    if getattr(sim, "cap", None) is None:
        return None
    out = []
    for i in range(sim.n):
        why = [w for _, w in sim.dropped[i].values()]
        out.append(dict(node=i, evicted=why.count("evicted"), rejected=why.count("rejected"),
                        min_fee=float(sim.min_fee[i]), pending=len(sim.mempool[i])))
    return out


def compute_run(seed: int, dist: str, policy: str, overrides: tuple = (), ref: dict | None = None) -> dict:
    """One disturbed run, packaged for the UI (the Simulation object itself is dropped)."""
    cfg = make_config(overrides)
    te = cfg.t_end(dist)
    if ref is None:
        ref = compute_reference(seed, te, overrides)
    r = run_one(cfg, seed, dist, policy, keep_log=True, pend_ref=ref["pend"])
    sim = r.pop("sim")
    m = dict(r["metrics"][f"{te:g}"])
    s = r["series"]
    pol = r["policy"]
    d = sim.scn.disturbance
    series = dict(t=np.asarray(s["t"], float), residue=np.asarray(s[f"res@{te:g}"], float),
                  pend=np.asarray(s["pend"], float), pend_ref=np.asarray(ref["pend"], float),
                  chain_ok=np.asarray(s["chain_ok"], bool), U=np.asarray(s["U"], float),
                  D=np.asarray(s["D"], float), B=np.asarray(s["B"], float))
    if cfg.mempool_cap is not None:
        for k in ("lost", "max_mp", "n_full"):
            series[k] = np.asarray(s[k], float)
        series["evdiv"] = np.asarray(s[f"evdiv@{te:g}"], float)
        series["gres"] = np.asarray(s[f"gres@{te:g}"], float)
    return dict(
        seed=int(seed), dist=dist, policy=policy, overrides=list(overrides), exploratory=bool(overrides),
        t_end=te, dist_start=cfg.dist_start, horizon=cfg.horizon, n_nodes=cfg.n_nodes,
        mempool_cap=cfg.mempool_cap, describe=demo.describe(cfg, seed, dist),
        disturbance=dict(kind=d.kind, start=d.start, end=d.end, group_a=list(d.group_a), nodes=list(d.nodes)),
        metrics=m, traffic_kB=traffic_kB(m), series=series,
        ext_a=extension_a(cfg, te, sim, ref),
        ext_c=capacity_metrics(r, te, cfg) if cfg.mempool_cap is not None else None,
        node_drops=node_drops(sim),
        log=[(float(t), str(msg)) for t, msg in r.get("log", [])],
        timeline=[(float(t), st_) for t, st_ in pol["timeline"]],
        alarms=[(float(t), src) for t, src in pol["alarms"]],
        incidents=[tuple(i) for i in pol["incidents"]],
        monitor_log=[(float(t), ev, int(a), int(b)) for t, ev, a, b in r["monitor_log"]],
        audit_log=np.asarray(r["audit_log"]) if "audit_log" in r else None,
        counters=dict(r["counters"]), policy_counters=dict(pol["counters"]), chain=dict(r["chain"]),
        wall=float(r["wall"]),
    )


# ----------------------------------------------------------------------------- runs (cached)
@_cache
def reference_run(seed: int, cutoff: float, overrides: tuple = ()) -> dict:
    return compute_reference(seed, cutoff, overrides)


@_cache
def policy_run(seed: int, dist: str, policy: str, overrides: tuple = ()) -> dict:
    """Cached on (seed, dist, policy, overrides). The clean reference is shared by every policy and every
    disturbance with the same t_end and overrides, so it is computed once."""
    cfg = make_config(overrides)
    ref = reference_run(seed, cfg.t_end(dist), overrides)
    return compute_run(seed, dist, policy, overrides, ref)


# ----------------------------------------------------------------------------- selection
@dataclass(frozen=True)
class Selection:
    """What the shared sidebar applied: disturbance, seed and the raw parameter values the user entered."""
    dist: str = "partition"
    seed: int = DEFAULT_SEED
    raw_overrides: tuple = field(default=())

    def overrides(self, dist: str | None = None) -> tuple:
        return normalize_overrides(dist or self.dist, dict(self.raw_overrides))

    def ignored(self, dist: str | None = None) -> list:
        return ignored_overrides(dist or self.dist, dict(self.raw_overrides))


def current_selection() -> Selection:
    """The selection applied in the sidebar (app.py), or the study defaults before the first apply."""
    import streamlit as st
    return st.session_state.get("selection", Selection())


# ----------------------------------------------------------------------------- derived views
fmt = demo.fmt


def outcome_row(m: dict) -> dict:
    """One row of demo.py's 'believed vs true' table, formatted exactly as demo.py prints it."""
    return {"detected": fmt(m["T_det"]), "declared": fmt(m["T_decl"]), "state ok": fmt(m["T_conv"]),
            "backlog ok": fmt(m["T_bk"]), "FRE_state": fmt(m["FRE_state"]), "FRE": fmt(m["FRE"]),
            "residue@decl": f"{m['resid_at_decl']:.0f}", "traffic": f"{traffic_kB(m):.0f}kB"}


def residue_at(run: dict, offset: float) -> float:
    """Evaluator residue (res@t_end) at t_end + offset, the instants used in results/verification.json."""
    t = run["series"]["t"]
    k = int(np.argmin(np.abs(t - (run["t_end"] + offset))))
    return float(run["series"]["residue"][k])


def excess_backlog(run: dict) -> np.ndarray:
    """Pending-set size of the disturbed history minus the clean history, clipped at 0 (as in demo.py)."""
    s = run["series"]
    n = min(len(s["pend"]), len(s["pend_ref"]))
    out = np.zeros(len(s["pend"]))
    out[:n] = np.clip(s["pend"][:n] - s["pend_ref"][:n], 0, None)
    return out


def monitor_unhealthy_steps(monitor_log: list) -> list:
    """(time, number of links the shared connectivity monitor considers unhealthy) at every change."""
    n = 0
    out = [(0.0, 0)]
    for t, ev, _a, _b in monitor_log:
        if ev == "edge_down":
            n += 1
        elif ev == "edge_up":
            n -= 1
        else:
            continue
        out.append((t, n))
    return out


def audit_trail(run: dict) -> list:
    """Policy log with times relative to the disturbance end, as demo.py prints it."""
    te = run["t_end"]
    return [(t - te, msg) for t, msg in run["log"]]


def _s(v: float) -> str:
    return f"{v:.0f} s"


def verdict(m: dict) -> str:
    """Plain-language verdict for one policy, generated only from its metrics."""
    fre_s, fre = m["FRE_state"], m["FRE"]
    if not m["detected"] and m["n_incidents"] == 0:
        s = "Never raised an alarm, so it reported 'recovered' throughout"
        if fre > 0:
            s += f"; false-recovery exposure {_s(fre)} (of which {_s(fre_s)} while residue remained)"
        else:
            s += "; the true state needed no recovery time, so there was no false-recovery exposure"
        return s + "."
    if m["decl_censored"]:
        if m["true_censored"]:
            return "Never declared recovery; the true state had not recovered by the end of the run either."
        return (f"Never declared recovery before the run ended, although the true state recovered "
                f"{_s(m['T_true'])} after the disturbance ended.")
    decl = m["T_decl"]
    if fre_s > 0:
        if m["conv_censored"]:
            s = (f"Declared recovered {_s(decl)} after the disturbance ended, but residue had not cleared "
                 f"by the end of the run ({_s(fre_s)} of false-recovery exposure on state)")
        elif decl < m["T_conv"]:
            s = (f"Declared recovered {_s(m['T_conv'] - decl)} before residue cleared "
                 f"(declared at +{_s(decl)}, residue cleared at +{_s(m['T_conv'])})")
        else:
            s = f"Reported 'recovered' for {_s(fre_s)} while residue remained"
        if m["resid_at_decl"] > 0:
            s += f"; {m['resid_at_decl']:.0f} residue transactions at declaration"
        return s + "."
    if fre > 0:
        return (f"No residue at declaration, but it reported 'recovered' for {_s(fre)} while backlog debt "
                f"remained (declared at +{_s(decl)}, backlog recovered at +{_s(m['T_bk'])}).")
    lag = decl - m["T_true"]
    if abs(lag) < 0.5:
        return "Declared recovered as the true state recovered; no false-recovery exposure."
    return (f"Declared recovered {_s(lag)} after the true state recovered (true state at +{_s(m['T_true'])}, "
            f"declared at +{_s(decl)}); no false-recovery exposure.")


def harm_line(run: dict) -> str:
    """Plain-language Extension A summary for one run, generated from its metrics."""
    e = run["ext_a"]["exposed"]["excess"]
    d = run["ext_a"]["during"]["excess"]
    s = (f"Transactions created from 120 s before the disturbance to 300 s after it waited on average "
         f"{e['mean']:.1f} s longer than in the clean history ({e['share_delayed']:.0%} of them longer); those "
         f"created during the disturbance {d['mean']:.1f} s longer.")
    if e["never_extra"]:
        s += f" {e['never_extra']} confirmed in the clean history but not by the end of this run."
    return s


__all__ = ["DISTURBANCES", "POLICIES", "COMPARE_POLICIES", "DIST_LABEL", "POLICY_LABEL", "TOPOLOGY_LABEL",
           "OVERRIDABLE", "DIST_PARAMS", "MODEL_PARAMS", "EXPLORATORY", "Selection", "base_config", "make_config",
           "normalize_overrides", "policy_run", "reference_run", "compute_run", "compute_reference", "verdict",
           "outcome_row", "fmt", "harm_line"]
