"""Tests for the frontend's non-UI code (app_lib/). The app only imports mh/; these tests check that what it shows
equals what the study pipeline computes."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo  # noqa: E402
from app_lib import results_io as io  # noqa: E402
from app_lib import runs as R  # noqa: E402
from app_lib import snapshots as S  # noqa: E402
from mh.calibration import load_config  # noqa: E402
from mh.config import DISTURBANCES  # noqa: E402
from mh.runner import run_one  # noqa: E402


def _eq(a, b):
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return a == b


# ------------------------------------------------------------------------------------------- settings
def test_overrides_never_touch_the_calibrated_config():
    before = load_config().as_dict()
    ov = R.normalize_overrides("loss", {"loss_p": 0.7, "topology": "erdos_renyi", "n_nodes": 20, "degree": 4,
                                        "tx_rate": 8.0, "block_capacity": 160, "mempool_cap": 356})
    cfg = R.make_config(ov)
    assert cfg.loss_p == 0.7 and cfg.topology == "erdos_renyi" and cfg.n_nodes == 20 and cfg.mempool_cap == 356
    assert load_config().as_dict() == before == R.base_config().as_dict()
    assert R.make_config(()) == load_config()


def test_override_normalisation_is_a_stable_cache_key():
    base = load_config()
    a = R.normalize_overrides("partition", {"n_nodes": 20, "loss_p": 0.9, "degree": 4, "mempool_cap": None})
    b = R.normalize_overrides("partition", {"degree": 4.0, "n_nodes": 20.0})
    assert a == b == (("n_nodes", 20),)                         # loss_p ignored for a partition; defaults dropped
    assert R.normalize_overrides("partition", {"tx_rate": base.tx_rate, "topology": base.topology}) == ()
    assert R.run_key(1000, "partition", "B1", a) == R.run_key(1000.0, "partition", "B1", b)
    assert R.normalize_overrides("loss", {"loss_p": 0.7}) == (("loss_p", 0.7),)
    with pytest.raises(ValueError):
        R.normalize_overrides("partition", {"topology": "watts_strogatz", "degree": 5})    # odd degree
    with pytest.raises(ValueError):
        R.normalize_overrides("partition", {"n_nodes": 11, "degree": 3})                  # 11 x 3 odd (regular)
    with pytest.raises(ValueError):
        R.normalize_overrides("partition", {"n_nodes": 500})
    with pytest.raises(ValueError):
        R.normalize_overrides("partition", {"horizon": 2000})
    assert R.ignored_overrides("partition", {"loss_p": 0.9}) == ["loss_p"]


def test_longer_disturbance_extends_the_horizon_by_the_same_amount():
    base = load_config()
    cfg = R.make_config(R.normalize_overrides("partition", {"dist_duration": 120.0}))
    assert cfg.horizon == base.horizon + 60.0 and cfg.t_end("partition") == 420.0


# ------------------------------------------------------------------------------------------- reproducibility
@pytest.fixture(scope="module")
def partition_1000():
    ref = R.compute_reference(1000, 360.0)
    return {p: R.compute_run(1000, "partition", p, (), ref) for p in R.COMPARE_POLICIES}


def test_app_metrics_equal_demo_py(partition_1000, capsys):
    rows = demo.one(load_config(), 1000, "partition", verbose=True, plot=False)
    printed = capsys.readouterr().out.splitlines()
    for p in R.COMPARE_POLICIES:
        line = next(ln for ln in printed if ln.startswith(f"{p:6s} "))
        assert line.split()[1:] == list(R.outcome_row(partition_1000[p]["metrics"]).values())
        for k, v in rows[p].items():
            assert _eq(partition_1000[p]["metrics"][k], v), (p, k)


def test_app_metrics_equal_verification_json(partition_1000):
    v = json.loads((ROOT / "results" / "verification.json").read_text())
    b1 = partition_1000["B1"]
    for r in v["residue_checks"]:
        assert R.residue_at(b1, r["t_after_end"]) == r["pipeline"] == r["hand"]
    m, fc = b1["metrics"], v["fre_check"]
    assert m["FRE_state"] == fc["FRE_state_pipeline"] == 173.0
    assert m["T_decl"] == fc["T_decl_pipeline"] and m["T_conv"] == fc["T_conv_pipeline"]


def test_extension_a_metrics_equal_the_stored_extension_runs(partition_1000):
    df = pd.read_csv(ROOT / "results" / "extensions" / "ext_a_runs.csv")
    for p in R.COMPARE_POLICIES:
        row = df[(df["sample"] == "heldout") & (df.seed == 1000) & (df.dist == "partition") & (df.policy == p)].iloc[0]
        a = partition_1000[p]["ext_a"]
        for w in ("before", "during", "after", "exposed"):
            assert a[w]["excess"]["mean"] == pytest.approx(row[f"{w}_x_mean"], rel=1e-12, abs=1e-12)
            assert a[w]["delay"]["mean"] == pytest.approx(row[f"{w}_mean"], rel=1e-12, abs=1e-12)
            assert a[w]["delay"]["never"] == row[f"{w}_never"]
        assert a["blocks"]["bcd"] == pytest.approx(row["blk_bcd"], rel=1e-12, abs=1e-12)


def test_extension_c_metrics_equal_the_stored_extension_runs():
    caps = io.cap_presets()
    df = pd.read_csv(ROOT / "results" / "extensions" / "ext_c_runs.csv", low_memory=False)
    ov = R.normalize_overrides("burst", {"mempool_cap": caps["loose"]})
    run = R.compute_run(3000, "burst", "SARA", ov)
    row = df[(df.cap_level == "loose") & (df.seed == 3000) & (df.history == "disturbed") & (df.dist == "burst")
             & (df.policy == "SARA")].iloc[0]
    c = run["ext_c"]
    for k in ("evicted", "rejected", "refused_deliveries", "unrepairable"):
        assert c[k] == row[k], k
    for k in ("evdiv_10", "evdiv_300", "lost_end", "evdiv_auc"):
        assert c[k] == pytest.approx(row[k]), k
    assert run["metrics"]["FRE_state"] == pytest.approx(row["FRE_state"])


# ------------------------------------------------------------------------------------------- replay
CASES = [("partition", "B1", ()), ("partition", "SARA", ()), ("isolation", "B2", ()), ("burst", "SARA", ()),
         ("loss", "B1", ()), ("burst", "B1", (("mempool_cap", 356),)),
         ("asymmetric", "SARA", (("degree", 4), ("n_nodes", 12), ("topology", "watts_strogatz")))]


@pytest.mark.parametrize("dist,policy,ov", CASES)
def test_replay_residue_matches_the_evaluator_series(dist, policy, ov):
    ov = tuple(sorted(ov))
    rp = S.compute_replay(1000, dist, policy, ov, interval=5.0)
    cfg = R.make_config(ov)
    te = cfg.t_end(dist)
    r = run_one(cfg, 1000, dist, policy)                     # the pipeline's own run, independent of the replay
    t, res = np.asarray(r["series"]["t"]), np.asarray(r["series"][f"res@{te:g}"])
    matched = 0
    for f in rp["frames"]:
        k = np.nonzero(t == f["t"])[0]
        if not len(k):
            continue
        if np.isnan(res[k[0]]):
            assert f["residue"] is None
        else:
            assert f["residue"] == int(res[k[0]]), (dist, policy, f["t"])
            matched += 1
    assert matched >= 100
    if dist == "partition" and policy == "B1":               # results/verification.json checkpoints
        by_t = {f["t"]: f["residue"] for f in rp["frames"]}
        assert [by_t[te + 10], by_t[te + 30], by_t[te + 120]] == [234, 221, 55]
    if dict(ov).get("mempool_cap"):
        # distinct transactions evicted per node, summed, can only be at most the run's eviction events
        last = rp["frames"][-1]
        assert 0 < sum(last["evicted"]) <= r["counters"]["evicted"]
        assert rp["residue_series"]["evdiv"].shape == res.shape


def _link_probe(sim):
    out = []
    for a, b in sim.edges:
        if sim.down[a][b] or sim.down[b][a]:
            out.append("down")
        elif sim.blackhole[a][b] or sim.blackhole[b][a]:
            out.append("blackholed")
        elif sim.loss[a][b] > 0 or sim.mult[a][b] != 1.0:
            out.append("degraded")
        else:
            out.append("healthy")
    return out


@pytest.mark.parametrize("dist", DISTURBANCES)
def test_derived_link_states_match_the_simulator(dist):
    rp = S.compute_replay(1001, dist, "B1", (), interval=2.0, probe=_link_probe)
    expect = {"cut": "down", "reconnecting": "down", "blackholed": "blackholed", "degraded": "degraded",
              "healthy": "healthy"}
    for f, states in zip(rp["frames"], rp["link_states"]):
        assert [expect[s] for s in states] == f["probe"], (dist, f["t"])


# ------------------------------------------------------------------------------------------- stored results
def test_loaders_report_missing_files_clearly(tmp_path):
    with pytest.raises(io.ResultsMissing, match="experiments/analyze.py"):
        io.load_json("numbers", tmp_path / "numbers.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(io.ResultsMissing, match="not valid JSON"):
        io.load_json("ext_numbers", bad)


def test_tables_only_select_stored_numbers():
    n = io.load_json("numbers")
    df, src = io.headline_table(n)
    row = df[(df.Disturbance == "Partition") & (df.Policy == "B1")].iloc[0]
    assert row["FRE_state, mean (s)"] == n["descriptive"]["partition"]["B1"]["FRE_state"]["mean"]
    assert "numbers.json" in src
    e = io.load_json("ext_numbers")
    df, _ = io.ext_b_table(e)
    assert len(df) == len(e["B"]["cells"])
    secs = io.md_sections(io.load_text("extensions_md"))
    assert {"preregistration", "changelog", "results", "discussion"} <= set(secs)
    assert io.cap_presets() == json.loads((ROOT / "results" / "extensions" / "ext_c_cap_calibration.json")
                                          .read_text())["caps"]
