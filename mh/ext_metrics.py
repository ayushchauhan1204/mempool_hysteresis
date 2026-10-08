"""Metrics for the extension experiments (results/extensions/). Not used by the main study.

Extension A (user-visible harm), computed from a finished Simulation:
  * confirmation delay of a transaction = time of the block that includes it on the final best chain
    minus its creation time (NaN if it is not on the final best chain at the horizon);
  * excess delay = disturbed-history delay minus clean-history delay of the same transaction id
    (common random numbers make the workload identical); an unconfirmed transaction's delay is
    censored at (horizon - creation time), so the excess is then a lower bound;
  * block-composition distance = 1 - |Cd & Cc| / |Cd | Cc|, where Ch is the set of shared-workload
    transactions in blocks of history h's final best chain mined in a given window.
Extension C (bounded mempools), computed from the series the evaluator records when cfg.mempool_cap is set.
"""
from __future__ import annotations

import math

import numpy as np

from .metrics import first_hold

PRE_WINDOW = 120.0        # Extension A: "before" = transactions created in the 120 s before the disturbance


# ------------------------------------------------------------------------------------------- Extension A
def best_chain(sim) -> list:
    """Blocks on the final best chain, genesis excluded, oldest first."""
    best, _ = sim.best_tip()
    out = []
    b = sim.blocks[best]
    while b.id != 0:
        out.append(b)
        b = sim.blocks[b.parent]
    return out[::-1]


def confirmation_times(sim) -> np.ndarray:
    """Per transaction id: mining time of the block that includes it on the final best chain (NaN if none)."""
    out = np.full(len(sim.created), np.nan)
    for b in best_chain(sim):
        for x in b.txs:
            out[x] = b.time
    return out


def windows(cfg, t_end: float) -> dict:
    """Creation-time windows (pre-registered): before / during / after the disturbance, and their union."""
    t0 = cfg.dist_start
    after = t_end + cfg.post_workload_window
    return dict(before=(t0 - PRE_WINDOW, t0), during=(t0, t_end), after=(t_end, after),
                exposed=(t0 - PRE_WINDOW, after))


def window_ids(created, is_base, lo, hi) -> np.ndarray:
    """Shared-workload transaction ids created in [lo, hi)."""
    created = np.asarray(created)
    return np.nonzero(np.asarray(is_base, bool) & (created >= lo) & (created < hi))[0]


def _q(x, q):
    return float(np.quantile(x, q)) if len(x) else math.nan


def delay_summary(created, conf_t, ids, horizon) -> dict:
    created = np.asarray(created, float)
    d = np.asarray(conf_t, float)[ids] - created[ids]
    ok = np.isfinite(d)
    cens = np.where(ok, d, horizon - created[ids])
    return dict(n=int(len(ids)), never=int((~ok).sum()),
                mean=float(d[ok].mean()) if ok.any() else math.nan,
                median=_q(d[ok], 0.5), p95=_q(d[ok], 0.95),
                mean_cens=float(cens.mean()) if len(ids) else math.nan)


def excess_summary(created, conf_d, conf_c, ids, horizon) -> dict:
    """Paired per-transaction excess delay, disturbed minus clean (censored at the horizon)."""
    created = np.asarray(created, float)[ids]
    dd = np.asarray(conf_d, float)[ids] - created
    dc = np.asarray(conf_c, float)[ids] - created
    lim = horizon - created
    e = np.where(np.isfinite(dd), dd, lim) - np.where(np.isfinite(dc), dc, lim)
    return dict(mean=float(e.mean()) if len(e) else math.nan, median=_q(e, 0.5), p95=_q(e, 0.95),
                share_delayed=float(np.mean(e > 0)) if len(e) else math.nan,
                never_extra=int(np.sum(~np.isfinite(dd) & np.isfinite(dc))))


def block_composition(chain_d, chain_c, lo, hi, is_base) -> dict:
    """Jaccard distance between the shared-workload contents of the two final best chains' blocks mined in
    [lo, hi), plus the transactions the clean history confirmed there but the disturbed one did not."""
    is_base = np.asarray(is_base, bool)

    def content(chain):
        s = set()
        nb = 0
        for b in chain:
            if lo <= b.time < hi:
                nb += 1
                s.update(x for x in b.txs if x < len(is_base) and is_base[x])
        return s, nb

    cd, nd = content(chain_d)
    cc, nc = content(chain_c)
    union = cd | cc
    return dict(bcd=(1.0 - len(cd & cc) / len(union)) if union else 0.0, displaced=len(cc - cd),
                added=len(cd - cc), blocks_d=nd, blocks_c=nc)


# ------------------------------------------------------------------------------------------- Extension C
def capacity_metrics(res: dict, t_end: float, cfg) -> dict:
    """Evicted-divergence summaries for one run (needs the series recorded when cfg.mempool_cap is set)."""
    s = res["series"]
    t = np.asarray(s["t"], float)
    ev = np.nan_to_num(np.asarray(s[f"evdiv@{t_end:g}"], float))
    gr = np.nan_to_num(np.asarray(s[f"gres@{t_end:g}"], float))
    U = np.asarray(s["U"], float)
    lost = np.asarray(s["lost"], float)
    out = {}
    for off in (0, 10, 60, 300):
        k = int(np.searchsorted(t, t_end + off - 1e-9))
        k = min(k, len(t) - 1)
        out[f"evdiv_{off}"] = float(ev[k])
        out[f"gres_{off}"] = float(gr[k])
        out[f"U_{off}"] = float(U[k])
        out[f"lost_{off}"] = float(lost[k])
    win = (t >= t_end - 1e-9) & (t <= t_end + cfg.residue_window + 1e-9)
    out["evdiv_auc"] = float(np.sum(ev[win]) * cfg.eval_interval)
    out["evdiv_end"] = float(ev[-1])
    out["U_end"] = float(U[-1])
    out["lost_end"] = float(lost[-1])
    tt, cens = first_hold(t, ev == 0, t_end, cfg.hold_window)
    out["T_evconv"] = tt - t_end
    out["evconv_censored"] = bool(cens)
    out["max_mp"] = float(np.max(s["max_mp"]))
    out["full_node_seconds"] = float(np.sum(s["n_full"]) * cfg.eval_interval)
    c = res["counters"]
    out["evicted"] = int(c.get("evicted", 0))
    out["rejected"] = int(c.get("rejected", 0))
    out["refused_deliveries"] = int(c.get("refused_deliveries", 0))
    pc = res["policy"]["counters"]
    out["unrepairable"] = int(pc.get("unrepairable", 0))
    if "audit_log" in res and len(res["audit_log"]):
        a = np.asarray(res["audit_log"])
        post = a[a[:, 0] >= t_end - 1e-9]
        out["max_tier_post"] = int(post[:, 4].max()) if len(post) else 0
        out["share_high_post"] = float(np.mean(post[:, 4] >= 2)) if len(post) else 0.0
    return out
