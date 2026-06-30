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
    """[audit-5 cross-artifact #4] When executive_brief is a truthy non-dict, trend_point raises and the
    try/except yields head={}, so the n_critical card silently defaulted to 0 while the bands chart (from
    health_scores) correctly showed Critical -- the same screen contradicted itself. n_critical now falls back
    to the band count."""
    from backend.summary import summarize
    s = summarize({"devices": {"sw1": {}, "sw2": {}},
                   "health_scores": [{"switch": "sw1", "band": "Critical", "score": 10},
                                     {"switch": "sw2", "band": "Critical", "score": 5}],
                   "executive_brief": "CORRUPT"})
    assert s["n_critical"] == s["bands"]["Critical"] == 2
