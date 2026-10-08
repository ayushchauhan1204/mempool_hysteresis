"""Phase 4 robustness sweeps (plan Section 7) on their own held-out seeds 2000-2049.

Each sweep varies one factor. Variants that change the clean operating envelope
(utilisation, network size) are recalibrated on the dev seeds first, exactly as in Phase 3.
Output: results/raw/sweeps/<name>/x_<value>/seed_*.pkl and results/sweeps.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.calibrate import calibrate  # noqa: E402
from experiments.common import load_dir, run_many  # noqa: E402
from mh.calibration import load_config  # noqa: E402

SEEDS = list(range(2000, 2050))
RAW = ROOT / "results" / "raw" / "sweeps"
POL = ("B1", "B2", "SARA")
METRICS = ("T_conv", "T_bk", "T_true", "FRE_state", "FRE", "residue_auc", "T_decl", "over_delay", "inband_kB",
           "conf_lat_mean")


def sweeps(base):
    return {
        "partition_duration": dict(
            title="Partition duration", xlabel="partition duration (s)", dists=("partition",),
            points=[(x, dict(dist_duration=float(x), horizon=300.0 + x + 660.0), False) for x in (15, 30, 60, 120, 240)]),
        "loss_lossy": dict(
            title="Loss with lossy transport", xlabel="message loss probability", dists=("loss",),
            points=[(x, dict(transport="lossy", loss_p=x), False) for x in (0.2, 0.4, 0.6, 0.8)]),
        "utilisation": dict(
            title="Block-space utilisation", xlabel="utilisation ρ", dists=("partition", "burst"),
            points=[(rho, dict(block_capacity=int(round(base.tx_rate * base.block_interval / rho))), True)
                    for rho in (0.5, 0.75, 0.9)]),
        "relay_reorged": dict(
            title="Reorged transactions re-announced", xlabel="relay_reorged", dists=("partition", "isolation"),
            points=[(x, dict(relay_reorged=x), False) for x in (False, True)]),
        "outage_mode": dict(
            title="Outage semantics", xlabel="outage mode", dists=("partition", "isolation"),
            points=[(x, dict(outage_mode=x), False) for x in ("reset", "buffered")]),
        "network_size": dict(
            title="Network size", xlabel="nodes N", dists=("partition",),
            points=[(x, dict(n_nodes=x), True) for x in (10, 20)]),
        # post-hoc sensitivity, added after the held-out run showed false incidents in clean runs:
        # the pre-specified calibration used 5 dev seeds; does a better-estimated tail change SARA?
        "calibration_dev_seeds": dict(
            title="Calibration sample (post hoc)", xlabel="dev seeds used for calibration",
            dists=("partition", "isolation", "loss", "latency", "asymmetric", "burst"),
            policies=("SARA",), clean_policies=("B1", "SARA"),
            points=[(x, dict(), x) for x in (5, 50)]),
    }


def summarize(df, dists):
    rng = np.random.default_rng(7)
    out = {}
    d = df[df.history == "disturbed"].copy()
    d["inband_kB"] = (d.announced * 36 + d.requested * 36 + d.transfers * 250) / 1000.0
    clean = df[df.history == "clean"]
    for pol in POL:
        sub = d[(d.policy == pol) & (d.dist.isin(dists))]
        if sub.empty:
            continue
        out[pol] = {}
        c0 = clean[(clean.policy == pol)]
        if not c0.empty:
            c0 = c0[c0.cutoff == c0.cutoff.min()]
            out[pol]["false_incidents_per_clean_run"] = float(c0.incidents_after_warmup.mean())
        for m in METRICS:
            v = sub.groupby("seed")[m].mean().values.astype(float)
            v = v[np.isfinite(v)]
            if len(v) == 0:
                out[pol][m] = dict(n=0)
                continue
            bs = rng.choice(v, (2000, len(v))).mean(axis=1)
            out[pol][m] = dict(n=int(len(v)), mean=float(v.mean()), median=float(np.median(v)),
                               ci95=[float(np.quantile(bs, .025)), float(np.quantile(bs, .975))])
        out[pol]["conv_censored_share"] = float(sub.conv_censored.astype(float).mean())
        per_dist = {}
        for dd in dists:
            s2 = d[(d.policy == pol) & (d.dist == dd)]
            per_dist[dd] = {m: float(s2[m].mean()) for m in ("T_conv", "FRE_state", "FRE", "residue_auc")}
        out[pol]["per_dist"] = per_dist
    return out


def main(only=None):
    base = load_config()
    result = {}
    p_out = ROOT / "results" / "sweeps.json"
    if p_out.exists():
        result = json.loads(p_out.read_text())
    for name, sw in sweeps(base).items():
        if only and name not in only:
            continue
        t0 = time.time()
        block = dict(title=sw["title"], xlabel=sw["xlabel"], dists=list(sw["dists"]), x=[], by_x={}, calibration={})
        for x, overrides, recal in sw["points"]:
            cfg = base.with_(**overrides)
            if recal is not False:
                dev = list(range(recal)) if (isinstance(recal, int) and not isinstance(recal, bool)) else None
                rep = calibrate(cfg, dev) if dev else calibrate(cfg)
                cfg = cfg.with_(**rep["values"])
                block["calibration"][str(x)] = rep["values"]
            out_dir = RAW / name / f"x_{x}"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "config.json").write_text(json.dumps(cfg.as_dict(), indent=1))
            print(f"[{name}] x={x}  ({len(SEEDS)} seeds)", flush=True)
            run_many(SEEDS, cfg, out_dir, dists=sw["dists"], policies=sw.get("policies", POL),
                     clean_policies=sw.get("clean_policies", ("B1",)), verbose=False)
            df, _, _ = load_dir(out_dir)
            block["x"].append(x)
            block["by_x"][str(x)] = summarize(df, sw["dists"])
        block["seconds"] = time.time() - t0
        result[name] = block
        p_out.write_text(json.dumps(result, indent=1, default=float))
        print(f"[{name}] done in {block['seconds']:.0f}s", flush=True)
    return result


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
