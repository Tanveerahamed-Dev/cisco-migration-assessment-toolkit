"""[audit-5 totality-crash batch — webapp] The UNAUTHENTICATED snapshot upload runs summarize() on every POST,
so a malformed / hostile snapshot section must degrade, never 500. (Unique basename: pytest derives the test
module name from the filename, which must not collide with the engine-side tests/test_audit5_totality.py.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable


def test_summarize_tolerates_truthy_nonlist_failure_impact():
    """[#1/#2 HIGH] _keystones used `(snap.get('failure_impact') or [])`, which only guards FALSY values -- a
    truthy non-list (int / str / dict in a malformed or hostile upload) flowed into the comprehension and 500'd
    the public POST /api/campaigns/{id}/snapshots. Must degrade via the file's own _as_list helper."""
    from backend.summary import summarize
    for bad in (5, "x", {"k": "v"}, 3.14):
        assert isinstance(summarize({"devices": {"c": {}}, "failure_impact": bad}), dict)


def test_summarize_n_critical_reconciles_with_bands_on_corrupt_exec_brief():
    """The engine withholds posture-backed critical facts under corrupt posture.

    Preserve both the genuine two-row partition and the stronger display rule:
    neither summary surface may turn the owner's withheld fact into a fake zero.
    """
    from backend.summary import summarize
    from cisco_toolkit import ssot, ui_projection
    snap = {"devices": {"sw1": {}, "sw2": {}},
            "health_scores": [{"switch": "sw1", "band": "Critical", "score": 10},
                              {"switch": "sw2", "band": "Critical", "score": 5}],
            "executive_brief": "CORRUPT"}
    partition = ssot.health_band_partition(snap)
    assert next(row["n"] for row in partition["bands"] if row["band"] == "Critical") == 2
    s = summarize(snap)
    owner = ui_projection.project_overview(snap)
    critical = next(row["n"] for row in owner["fleet_health"]["bands"] if row["band"] == "Critical")
    assert critical["state"] != "published" and critical["value"] is None and critical["reason"]
    assert s["n_critical"] is None and s["bands"]["Critical"] is None
    assert s["assessment"]["facts"] == owner["facts"]
    assert s["assessment"]["bands"] == owner["fleet_health"]["bands"]


def test_summarize_preserves_a_published_positive_critical_count():
    from backend.summary import summarize
    snap = {"devices": {"sw1": {}, "sw2": {}},
            "health_scores": [{"switch": "sw1", "band": "Critical", "score": 10},
                              {"switch": "sw2", "band": "Critical", "score": 5}],
            "executive_brief": {"posture": {"avg_health": 7.5, "n_critical": 2,
                                            "n_poor": 0, "worst_band": "Critical"}}}
    s = summarize(snap)
    assert s["n_critical"] == s["bands"]["Critical"] == 2
    assert s["assessment"]["facts"]["n_critical"]["fact"]["state"] == "published"
