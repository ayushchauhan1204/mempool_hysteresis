"""Extension B: scale and topology robustness sweep (pre-registered in results/extensions/EXTENSIONS.md).

Cells: topology x n_nodes x degree with the transaction rate scaled with n (block capacity scaled with it, so
utilisation stays 0.75), plus a fixed-total-rate line; B1, B2 and SARA (calibrated values fixed), plus the clean
B1 and clean SARA histories, on seeds 3000-3029. Disturbances: partition / isolation / asymmetric in the 10- and
20-node cells, partition only in the 50-node cells (scope change logged in EXTENSIONS.md: compute time).
Secondary: SARA re-calibrated on dev seeds 0-4 for the three 50-node, degree-4, scaled-rate cells, partition only
(clearly labelled "recalibrated").

    python experiments/ext_b_scale.py               # primary, then secondary
    python experiments/ext_b_scale.py --primary     # primary only
    python experiments/ext_b_scale.py --secondary   # secondary only
Raw per-job results: results/extensions/raw/B/ (resumable). Output: results/extensions/ext_b_runs.csv and
results/extensions/ext_b_cells.json.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.calibrate import calibrate  # noqa: E402
from mh.calibration import load_config  # noqa: E402
from mh.runner import run_one  # noqa: E402
from mh.scenario import build_scenario  # noqa: E402

OUT = ROOT / "results" / "extensions"
RAW = OUT / "raw" / "B"
TOPOLOGIES = ("random_regular", "erdos_renyi", "watts_strogatz")
NS = (10, 20, 50)
DEGREES = (4, 8)
DISTS = ("partition", "isolation", "asymmetric")
POLICIES = ("B1", "B2", "SARA")
SEEDS = tuple(range(3000, 3030))
MAIN_CELL = "random_regular_n10_d4_scaled"
SECONDARY_CELLS = tuple(f"{t}_n50_d4_scaled" for t in TOPOLOGIES)
SECONDARY_DISTS = ("partition",)


def cell_dists(cell):
    """Disturbances run in a cell: partition only at 50 nodes (compute time; logged in EXTENSIONS.md)."""
    return ("partition",) if cell["n_nodes"] >= 50 else DISTS
METRICS = ("T_det", "detected", "T_decl", "decl_censored", "T_conv", "conv_censored", "T_bk", "T_true",
           "FRE", "FRE_state", "FRE_backlog", "over_delay", "over_delay_state", "resid_at_decl", "residue_auc",
           "resid_10", "resid_60", "n_incidents", "incidents_after_warmup", "reopened", "announced", "requested",
           "transfers")


def cells():
    base = load_config()
    out = []

    def add(topo, n, d, load):
        if load == "scaled":
            rate, cap = base.tx_rate * n / base.n_nodes, base.block_capacity * n // base.n_nodes
        else:
            rate, cap = base.tx_rate, base.block_capacity
        out.append(dict(cell=f"{topo}_n{n}_d{d}_{load}", topology=topo, n_nodes=n, degree=d, load=load,
                        overrides=dict(topology=topo, n_nodes=n, degree=d, tx_rate=rate, block_capacity=cap)))
    for topo in TOPOLOGIES:
        for n in NS:
            for d in DEGREES:
                add(topo, n, d, "scaled")
    for n in (20, 50):
        add("random_regular", n, 4, "fixed")
    return out


def cost(cell):
    """Rough relative run cost (for scheduling the longest jobs first)."""
    o = cell["overrides"]
    return o["n_nodes"] * o["degree"] * o["tx_rate"]


def _row(cell, variant, seed, history, dist, pol, r, cfg):
    m = r["metrics"][f"{cfg.t_end(dist):g}"]
    row = dict(cell=cell["cell"], topology=cell["topology"], n_nodes=cell["n_nodes"], degree=cell["degree"],
               load=cell["load"], tx_rate=cfg.tx_rate, block_capacity=cfg.block_capacity, variant=variant,
               seed=seed, history=history, dist=dist or "", policy=pol, wall=r["wall"])
    for k in METRICS:
        row[k] = m[k]
    return row


def run_job(job):
    cell, variant, seed, sara_values = job
    path = RAW / variant / cell["cell"] / f"seed_{seed:05d}.pkl"
    if path.exists():
        return str(path)
    cfg = load_config().with_(**cell["overrides"])
    if sara_values:
        cfg = cfg.with_(**sara_values)
    dists = cell_dists(cell) if variant == "calibrated" else SECONDARY_DISTS
    cutoffs = [cfg.t_end(d) for d in dists][:1]         # all three disturbances end at the same t_end
    rows = []
    ref = run_one(cfg, seed, None, "B1", cutoffs=cutoffs)
    pend_ref = ref["series"]["pend"]
    scn = build_scenario(cfg, seed, None)
    g = nx.Graph(scn.edges)
    graph = dict(n_edges=len(scn.edges), mean_degree=2 * len(scn.edges) / cfg.n_nodes,
                 max_degree=max(len(p) for p in scn.peers), diameter=nx.diameter(g))
    policies = POLICIES if variant == "calibrated" else ("SARA",)
    if variant == "calibrated":
        rows.append(_row(cell, variant, seed, "clean", None, "B1", ref, cfg) | graph)
    r = run_one(cfg, seed, None, "SARA", cutoffs=cutoffs, pend_ref=pend_ref)
    rows.append(_row(cell, variant, seed, "clean", None, "SARA", r, cfg) | graph)
    for dist in dists:
        for pol in policies:
            r = run_one(cfg, seed, dist, pol, pend_ref=pend_ref)
            rows.append(_row(cell, variant, seed, "disturbed", dist, pol, r, cfg) | graph)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(rows, f)
    os.replace(tmp, path)
    return str(path)


def _calibrate_cell(cell):
    cfg = load_config().with_(**cell["overrides"])
    rep = calibrate(cfg)                                  # dev seeds 0-4, exactly as in Phase 3
    return cell["cell"], rep


def run_jobs(jobs, procs):
    t0 = time.perf_counter()
    with Pool(procs) as pool:
        for k, _ in enumerate(pool.imap_unordered(run_job, jobs), 1):
            if k % 20 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)} jobs  {time.perf_counter() - t0:.0f}s", flush=True)


def collect(all_cells):
    rows = []
    for p in sorted(RAW.glob("*/*/seed_*.pkl")):
        with open(p, "rb") as f:
            rows += pickle.load(f)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "ext_b_runs.csv", index=False)
    print(f"wrote {OUT / 'ext_b_runs.csv'} ({len(df)} rows)")


def main(primary=True, secondary=True):
    OUT.mkdir(parents=True, exist_ok=True)
    all_cells = sorted(cells(), key=cost, reverse=True)
    procs = max(1, min(14, (os.cpu_count() or 2) - 2))
    meta_path = OUT / "ext_b_cells.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update(seeds=list(SEEDS), dists=list(DISTS), policies=list(POLICIES), main_cell=MAIN_CELL,
                cells={c["cell"]: {k: v for k, v in c.items() if k != "cell"} | {"dists": list(cell_dists(c))}
                       for c in all_cells},
                secondary_cells=list(SECONDARY_CELLS), secondary_dists=list(SECONDARY_DISTS),
                recalibration=meta.get("recalibration", {}))
    meta_path.write_text(json.dumps(meta, indent=1))
    if primary:
        print(f"primary: {len(all_cells)} cells x {len(SEEDS)} seeds", flush=True)
        run_jobs([(c, "calibrated", s, None) for c in all_cells for s in SEEDS], procs)
    if secondary:
        todo = [c for c in all_cells if c["cell"] in SECONDARY_CELLS and c["cell"] not in meta["recalibration"]]
        if todo:
            print(f"secondary: re-calibrating SARA for {len(todo)} cells on dev seeds 0-4", flush=True)
            with Pool(min(procs, len(todo))) as pool:
                for name, rep in pool.imap_unordered(_calibrate_cell, todo):
                    meta["recalibration"][name] = rep
                    meta_path.write_text(json.dumps(meta, indent=1))
                    print(f"  calibrated {name}: {rep['values']}", flush=True)
        jobs = [(c, "recalibrated", s, meta["recalibration"][c["cell"]]["values"])
                for c in all_cells if c["cell"] in SECONDARY_CELLS for s in SEEDS]
        print(f"secondary: {len(jobs)} jobs", flush=True)
        run_jobs(jobs, procs)
    collect(all_cells)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", action="store_true")
    ap.add_argument("--secondary", action="store_true")
    a = ap.parse_args()
    both = not (a.primary or a.secondary)
    main(primary=a.primary or both, secondary=a.secondary or both)
