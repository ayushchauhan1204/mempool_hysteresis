"""Per-run metrics, computed from the evaluator's true-state series and the policy timeline.

Definitions follow Section 5 of the implementation plan. Times are seconds after the
disturbance ends (t_end) unless stated otherwise. NaN means "not reached before the
horizon" (censored) or "not applicable"; censoring flags are returned alongside.
"""
from __future__ import annotations

import math

import numpy as np


def first_hold(t, ok, start, hold):
    """First sample time >= start from which `ok` holds continuously for `hold` seconds.

    Returns (time, censored). If no qualifying run exists before the series ends, the
    result is censored and the last sample time is returned.
    """
    t = np.asarray(t, float)
    ok = np.asarray(ok, bool)
    k0 = int(np.searchsorted(t, start - 1e-9))
    run = None
    for k in range(k0, len(t)):
        if ok[k]:
            if run is None:
                run = k
            if t[k] - t[run] >= hold - 1e-9:
                return float(t[run]), False
        else:
            run = None
    return float(t[-1]), True


def status_at(timeline, t):
    s = timeline[0][1]
    for tt, st in timeline:
        if tt <= t + 1e-12:
            s = st
        else:
            break
    return s


def recovered_measure(timeline, a, b):
    """Seconds within [a, b] during which the policy's status was 'recovered'."""
    if b <= a:
        return 0.0
    pts = [(tt, st) for tt, st in timeline]
    total = 0.0
    cur = status_at(pts, a)
    cur_t = a
    for tt, st in pts:
        if tt <= a:
            continue
        if tt >= b:
            break
        if cur == "recovered":
            total += tt - cur_t
        cur, cur_t = st, tt
    if cur == "recovered":
        total += b - cur_t
    return total


def run_metrics(res: dict, t_end: float, cfg, dist_start: float, pend_ref=None) -> dict:
    """Compute the plan's metrics for one run at a given t_end cutoff.

    Backlog truth is counterfactual when `pend_ref` (the paired clean run's pending-set
    size, sampled at the same instants) is given: backlog has recovered once the disturbed
    history holds no more pending transactions than the clean history, held for
    `hold_window`. This avoids grading SARA with its own backlog limit beta; the
    beta-based time is kept as T_bk_beta for reference.
    """
    s = res["series"]
    t = np.asarray(s["t"], float)
    key = f"res@{t_end:g}"
    resid = np.asarray(s[key], float)
    chain_ok = np.asarray(s["chain_ok"], bool)
    B = np.asarray(s["B"], float)
    D = np.asarray(s["D"], float)
    hold = cfg.hold_window

    post = t >= t_end - 1e-9
    resid_post = np.where(np.isnan(resid), 0, resid)
    t_conv_abs, conv_cens = first_hold(t, (resid_post == 0) & chain_ok, t_end, hold)
    t_bkb_abs, _ = first_hold(t, B <= cfg.beta, t_end, hold)
    if pend_ref is not None:
        pend = np.asarray(s["pend"], float)
        ref = np.asarray(pend_ref, float)
        m_ = min(len(pend), len(ref))
        excess = np.full(len(t), np.inf)
        excess[:m_] = pend[:m_] - ref[:m_]
        t_bk_abs, bk_cens = first_hold(t, excess <= 0, t_end, hold)
        excess_auc = float(np.sum(np.clip(excess[:m_][(t[:m_] >= t_end) & (t[:m_] <= t_end + cfg.residue_window)], 0, None)) * cfg.eval_interval)
    else:
        t_bk_abs, bk_cens = first_hold(t, B <= cfg.beta, t_end, hold)
        excess_auc = math.nan
    T_conv = t_conv_abs - t_end
    T_bk = t_bk_abs - t_end
    T_true = max(T_conv, T_bk)
    true_cens = (conv_cens and T_conv >= T_bk) or (bk_cens and T_bk >= T_conv)

    win = post & (t <= t_end + cfg.residue_window + 1e-9)
    dt = cfg.eval_interval
    residue_auc = float(np.nansum(resid[win]) * dt)
    D_post = float(np.mean(D[win])) if win.any() else math.nan
    during = (t >= dist_start) & (t < t_end)
    D_during = float(np.mean(D[during])) if during.any() else math.nan
    resid_at = {}
    for off in (0, 10, 30, 60, 120, 300):
        k = int(np.searchsorted(t, t_end + off - 1e-9))
        resid_at[off] = float(resid[k]) if k < len(t) else math.nan

    # policy-side quantities
    pol = res["policy"]
    tl = pol["timeline"]
    incidents = pol["incidents"]
    det = [a for a, src in pol["alarms"] if a >= dist_start - 1e-9]
    T_det = (det[0] - dist_start) if det else math.nan
    final_status = tl[-1][1]
    if final_status == "recovered":
        last_close = tl[-1][0]
        T_decl = max(0.0, last_close - t_end)
        decl_cens = False
    else:
        T_decl = cfg.horizon - t_end
        decl_cens = True
    FRE = recovered_measure(tl, t_end, t_end + T_true)
    FRE_state = recovered_measure(tl, t_end, t_end + T_conv)
    FRE_backlog = recovered_measure(tl, t_end, t_end + T_bk)
    over_delay = max(0.0, T_decl - T_true)
    over_delay_state = max(0.0, T_decl - T_conv)
    k = int(np.searchsorted(t, t_end + T_decl - 1e-9))
    resid_decl = float(resid_post[min(k, len(t) - 1)])
    premature = bool(resid_decl > 0 or T_decl < T_true)
    false_alarms = sum(1 for o, c, src in incidents if o < dist_start - 1e-9 and o >= cfg.eval_start)
    incidents_after_warmup = sum(1 for o, c, src in incidents if o >= cfg.eval_start)

    ctr = pol["counters"]
    out = dict(
        T_conv=T_conv, conv_censored=conv_cens, T_bk=T_bk, bk_censored=bk_cens,
        T_bk_beta=t_bkb_abs - t_end, excess_backlog_auc=excess_auc,
        T_true=T_true, true_censored=true_cens, T_decl=T_decl, decl_censored=decl_cens,
        FRE=FRE, FRE_state=FRE_state, FRE_backlog=FRE_backlog, over_delay=over_delay,
        over_delay_state=over_delay_state, resid_at_decl=resid_decl, premature=premature,
        T_det=T_det, detected=not math.isnan(T_det), residue_auc=residue_auc,
        D_post=D_post, D_during=D_during, reopened=pol["reopened"], n_incidents=len(incidents),
        false_alarms_pre=false_alarms, incidents_after_warmup=incidents_after_warmup,
        transfers=ctr["transfers"], unnecessary=ctr["unnecessary"], requested=ctr["requested"],
        announced=ctr["announced"], recovery_msgs=ctr["messages"], rounds=ctr["rounds"],
        snapshot_ids=ctr["snapshot_ids"], snapshot_delta_ids=ctr.get("snapshot_delta_ids", 0),
        resyncs=ctr["resyncs"],
    )
    for off, v in resid_at.items():
        out[f"resid_{off}"] = v

    # downstream effect on the identical post-recovery workload
    w = res["post_workload"][f"{t_end:g}"]
    lat = np.asarray(w["conf_latency"], float)
    out["conf_lat_mean"] = float(np.nanmean(lat)) if np.isfinite(lat).any() else math.nan
    out["conf_lat_p95"] = float(np.nanpercentile(lat, 95)) if np.isfinite(lat).any() else math.nan
    out["unconfirmed_post"] = int(np.sum(~np.isfinite(lat)))
    # censored latency: unconfirmed count as (horizon - created)
    cens = np.where(np.isfinite(lat), lat, np.asarray(w["cens_latency"], float))
    out["conf_lat_mean_cens"] = float(np.mean(cens)) if len(cens) else math.nan
    prop = np.asarray(w["prop_latency"], float)
    out["prop_lat_mean"] = float(np.nanmean(prop)) if np.isfinite(prop).any() else math.nan
    out["stale_rate"] = res["chain"]["stale_rate"]
    out["reorgs"] = res["chain"]["reorgs"]
    out["reorg_returned"] = res["chain"]["reorg_returned"]
    return out
