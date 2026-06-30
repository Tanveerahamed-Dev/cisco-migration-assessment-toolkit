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
