"""Shared experiment driver: run every (history, disturbance, policy) for a seed and store
compact results (metric rows + the curves the figures need) one pickle per seed."""
from __future__ import annotations

import os
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mh.config import DISTURBANCES, POLICIES  # noqa: E402
from mh.runner import run_one  # noqa: E402

CLEAN_POLICIES = ("B1", "SARA", "SARA-D", "SARA-R", "SARA-V")   # B2 == B1 without a disturbance
SERIES_POLICIES = ("B1", "B2", "SARA")
SERIES_KEYS = ("U", "D", "B", "chain_ok", "pend")


def run_seed(args):
    seed, cfg, dists, policies, clean_policies, out_dir = args
    path = Path(out_dir) / f"seed_{seed:05d}.pkl"
    if path.exists():
        return str(path)
    t0 = time.perf_counter()
    cutoffs = sorted({cfg.t_end(d) for d in dists})
    rows, curves, post = [], {}, {}

    def keep(r, hist, dist, pol):
        for c in r["cutoffs"]:
            m = dict(r["metrics"][f"{c:g}"])
            m.update(seed=seed, history=hist, dist=dist, policy=pol, cutoff=c)
            if dist is None and c != cfg.t_end(None) and hist == "clean":
                pass
            rows.append(m)
        if pol in SERIES_POLICIES or (hist == "clean" and pol in ("B1", "SARA")):
            s = r["series"]
            entry = {k: np.asarray(s[k]) for k in SERIES_KEYS}
            entry["t"] = np.asarray(s["t"])
            for c in r["cutoffs"]:
                entry[f"res@{c:g}"] = np.asarray(s[f"res@{c:g}"])
            curves[(hist, dist, pol)] = entry
            for c in r["cutoffs"]:
                w = r["post_workload"][f"{c:g}"]
                post[(hist, dist, pol, c)] = (w["ids"], w["conf_latency"].astype(np.float32))

    # the clean no-intervention run is the counterfactual for every backlog comparison
    ref = run_one(cfg, seed, None, "B1", cutoffs=cutoffs)
    pend_ref = ref["series"]["pend"]
    if "B1" in clean_policies:
        keep(ref, "clean", None, "B1")
    for pol in clean_policies:
        if pol == "B1":
            continue
        r = run_one(cfg, seed, None, pol, cutoffs=cutoffs, pend_ref=pend_ref)
        keep(r, "clean", None, pol)
    for dist in dists:
        for pol in policies:
            r = run_one(cfg, seed, dist, pol, pend_ref=pend_ref)
            keep(r, "disturbed", dist, pol)
    with open(path, "wb") as f:
        pickle.dump(dict(seed=seed, rows=rows, curves=curves, post=post,
                         wall=time.perf_counter() - t0), f, protocol=pickle.HIGHEST_PROTOCOL)
    return str(path)


def run_many(seeds, cfg, out_dir, dists=DISTURBANCES, policies=POLICIES, clean_policies=CLEAN_POLICIES,
             procs=None, verbose=True):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    procs = procs or max(1, (os.cpu_count() or 2))
    jobs = [(s, cfg, tuple(dists), tuple(policies), tuple(clean_policies), str(out_dir)) for s in seeds]
    t0 = time.perf_counter()
    done = 0
    with Pool(procs) as pool:
        for _ in pool.imap_unordered(run_seed, jobs):
            done += 1
            if verbose and (done % max(1, len(jobs) // 20) == 0 or done == len(jobs)):
                el = time.perf_counter() - t0
                print(f"  {done}/{len(jobs)} seeds  {el:.0f}s elapsed  ~{el / done * (len(jobs) - done):.0f}s left",
                      flush=True)
    return out_dir


def load_dir(out_dir):
    import pandas as pd
    rows, curves, post = [], {}, {}
    for p in sorted(Path(out_dir).glob("seed_*.pkl")):
        with open(p, "rb") as f:
            d = pickle.load(f)
        rows += d["rows"]
        for k, v in d["curves"].items():
            curves[(d["seed"],) + k] = v
        for k, v in d["post"].items():
            post[(d["seed"],) + k] = v
    return pd.DataFrame(rows), curves, post
