"""With every extension switched off (the defaults), the simulator must reproduce the regression snapshot that was
recorded before the extensions were added, bit for bit (see tests/regression_snapshot.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regression_snapshot import SNAPSHOT, compute_snapshot  # noqa: E402

# extension settings that did not exist when the snapshot was recorded, with their "off" defaults
EXTENSION_DEFAULTS = {"topology": "random_regular", "ws_rewire": 0.1, "mempool_cap": None}


@pytest.fixture(scope="module")
def snapshots():
    return json.loads(SNAPSHOT.read_text()), compute_snapshot()


def test_config_defaults_unchanged(snapshots):
    want, got = snapshots
    for k, v in want["config"].items():
        assert got["config"][k] == v, k
    for k, v in got["config"].items():
        if k not in want["config"]:
            assert k in EXTENSION_DEFAULTS and v == EXTENSION_DEFAULTS[k], f"new config field {k}={v!r} is not off"


def test_scenarios_unchanged(snapshots):
    want, got = snapshots
    assert got["scenarios"] == want["scenarios"]


def test_runs_bit_identical(snapshots):
    want, got = snapshots
    assert sorted(got["runs"]) == sorted(want["runs"])
    for key, rec in want["runs"].items():
        assert got["runs"][key] == rec, key
