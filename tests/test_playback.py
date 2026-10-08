"""Tests for the playback helpers (app_lib/playback.py). Playback is display only: every frame shows the stored
result up to the playback clock, and the last frame must be the static result with demo.py's values."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_lib import playback as PB  # noqa: E402
from app_lib import plots as P  # noqa: E402
from app_lib import runs as R  # noqa: E402


@pytest.fixture(scope="module")
def partition_1000():
    ref = R.compute_reference(1000, 360.0)
    return {p: R.compute_run(1000, "partition", p, (), ref) for p in R.COMPARE_POLICIES}


# ------------------------------------------------------------------------------------------- pure helpers
def test_clocks_end_with_the_static_frame():
    c = PB.clocks(-90.0, 480.0)
    assert len(c) == PB.N_FRAMES and c[-1] is None and c[0] == -90.0
    assert all(a < b for a, b in zip(c[:-2], c[1:-1])) and c[-2] < 480.0
    assert PB.clocks(0.0, 1.0, n=1) == [None]


def test_frame_indices_cover_first_and_last_snapshot():
    for n_items in (1, 5, 48, 49, 144, 300):
        idx = PB.frame_indices(n_items)
        assert idx[0] == 0 and idx[-1] == n_items - 1
        assert all(a < b for a, b in zip(idx, idx[1:])) and len(idx) <= PB.N_FRAMES


def test_clock_marker_carries_the_clock():
    assert PB.clock_marker(43.21) == '<div class="mh-clock" data-from="43.21"></div>'
    moving = PB.clock_marker(-90.0, 480.0, 3.5, 1.7e12)
    assert 'data-from="-90"' in moving and 'data-to="480"' in moving and 'data-secs="3.5"' in moving


def test_rows_until_and_revealed():
    rows = [(-59.0, "alarm"), (6.0, "recovered"), (200.0, "x")]
    assert PB.rows_until(rows, None) == rows
    assert PB.rows_until(rows, 6.0) == rows[:2]
    assert PB.rows_until(rows, -100.0) == []
    assert PB.revealed(None, None) and not PB.revealed(None, 479.0)
    assert PB.revealed(6.0, 6.0) and not PB.revealed(6.0, 5.9)


# ------------------------------------------------------------------------------------------- on the study run
def test_final_frame_shows_demo_py_values(partition_1000):
    """Seed 1000, partition: the last frame of every policy shows exactly demo.py's row."""
    expect = {"B1": dict(detected="1s", declared="6s", **{"state ok": "179s"}, FRE_state="173s",
                         **{"residue@decl": "234"}),
              "SARA": dict(declared="44s", **{"state ok": "8s"}, FRE_state="0s")}
    for p, run in partition_1000.items():
        m = run["metrics"]
        row = R.outcome_row(m)
        times = PB.reveal_times(m, run["t_end"] - run["dist_start"])
        assert PB.masked_row(row, times, None) == row
        for k, v in expect.get(p, {}).items():
            assert row[k] == v, (p, k)
    b1 = partition_1000["B1"]
    assert [R.residue_at(b1, o) for o in (10, 30, 120)] == [234.0, 221.0, 55.0]


def test_values_are_pending_until_the_clock_passes_their_event(partition_1000):
    dur = 60.0
    b1, sara = partition_1000["B1"]["metrics"], partition_1000["SARA"]["metrics"]
    t1 = PB.reveal_times(b1, dur)
    at = lambda m, t, c: PB.masked_row(R.outcome_row(m), t, c)      # noqa: E731
    assert at(b1, t1, -59.0)["detected"] == "1s"                     # first alarm 1 s after the start (t_end - 59 s)
    assert at(b1, t1, -60.0)["detected"] == PB.PENDING
    mid = at(b1, t1, 100.0)
    assert mid["declared"] == "6s" and mid["residue@decl"] == "234"
    assert mid["state ok"] == mid["FRE_state"] == PB.PENDING and mid["traffic"] == PB.PENDING
    assert at(b1, t1, 179.0)["FRE_state"] == "173s"
    assert PB.verdict_time(b1) == 179.0                              # "declared 173 s before residue cleared"
    ts = PB.reveal_times(sara, dur)
    early = at(sara, ts, 10.0)
    assert early["state ok"] == "8s" and early["FRE_state"] == "0s" and early["declared"] == PB.PENDING
    assert at(sara, ts, 44.0)["declared"] == "44s"


def test_playback_shows_the_static_figure_itself(partition_1000):
    """The chart is drawn once, as the static figure, and only covered beyond the clock during playback, so the
    last frame is the static figure. Building it twice gives the same figure (nothing random or time-dependent)."""
    for build in (lambda: P.run_figure(partition_1000["B1"], "dark"),
                  lambda: P.compare_figure(partition_1000, "light")):
        assert build().to_dict() == build().to_dict()
    x0, x1 = P.x_range(partition_1000["B1"])
    assert (x0, x1) == (-90.0, 480.0)
    c = PB.clocks(x0, x1)
    assert c[0] == x0 and c[-1] is None and max(c[:-1]) < x1
