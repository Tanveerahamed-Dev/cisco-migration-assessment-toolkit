"""G13: the cutover plan joins a wave to its move group by the owner's label (compute_move_groups writes
``group``), not by switch overlap alone. A wave whose switches are all 'homing unknown' and that has no
readiness row has an empty switch set, so the overlap-only join matched no group and reported 0 endpoints."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import cutover  # noqa: E402


def test_wave_joins_its_move_group_by_the_owner_label():
    snap = {
        "move_groups": [{"group": "Group 1", "switches": ["a"], "endpoints": 5},
                        {"group": "Group 2", "switches": ["x"], "endpoints": 7}],
        "wave_sequencing": [{"group": "Group 2", "make_before_break": [], "hard_cutover": [],
                             "homing_unknown": ["x"], "hard_cutover_endpoints": 0}],
    }
    plan = cutover.build_plan(snap)
    wave = next(w for w in plan["waves"] if w["group"] == "Group 2")
    assert wave["endpoints"] == 7


def test_unlabelled_legacy_snapshot_still_joins_by_switch_overlap():
    snap = {
        "move_groups": [{"switches": ["a"], "endpoints": 5}, {"switches": ["x"], "endpoints": 7}],
        "wave_sequencing": [{"group": "Group 2", "make_before_break": ["x"], "hard_cutover": [],
                             "hard_cutover_endpoints": 0}],
    }
    wave = cutover.build_plan(snap)["waves"][0]
    assert wave["endpoints"] == 7


def test_written_label_mismatch_never_borrows_endpoints_by_overlap():
    groups = [{"group": "Group 1", "switches": ["a"], "endpoints": 5}]
    assert cutover._match_move_group({"a"}, groups, "Group 99") == {}
