"""[crash-safety fuzz, 2026-07-28 -- webapp half] A malformed UPLOAD must degrade, never 500.

Companion to `tests/test_crash_safety_fuzz.py` (which carries the full method + class taxonomy).
These are the webapp-reachable instances, and they are the worst ones in the sweep: the snapshot is
STORED, the routes below are read on every dashboard load, and an uncaught exception escapes as an
unhandled HTTP 500 -- so ONE malformed upload permanently bricks that snapshot's cockpit.

`_keystones` is the shared CHOKE POINT: `summarize` (dashboard), `cutover.build_plan` (/cutover) and
`execution.start_run` (/executions) all funnel through it, so the single `_hkey` guard there closes
three routes at once. Each case below RAISED before its guard; reverting the guard re-raises it.
"""
import pytest

INF = float("inf")
BIG = 10 ** 400
UNHASHABLE = [{"k": 1}, [1], {}, []]
IDS = ["dict", "list", "emptydict", "emptylist"]


@pytest.mark.parametrize("bad", UNHASHABLE, ids=IDS)
def test_keystones_choke_point_tolerates_unhashable_severity(bad):
    """`_SEV_RANK.get(r.get("severity"))` HASHES its argument, so a dict/list severity raised
    `TypeError: unhashable type` inside the sort key of `summary._keystones` -- the one helper
    behind THREE unauthenticated read routes. All three must degrade together."""
    from webapp.backend import cutover, execution, summary
    snap = {"devices": {"h": {}},
            "failure_impact": [{"host": "h", "severity": bad, "stranded": 3, "vlans_impacted": 1}]}
    assert isinstance(summary.summarize(snap), dict)
    assert isinstance(cutover.build_plan(snap), dict)
    assert isinstance(execution.start_run(snap, "L", "op"), dict)


@pytest.mark.parametrize("bad", UNHASHABLE, ids=IDS)
def test_summarize_tolerates_unhashable_readiness(bad):
    """`r.get("readiness") in readiness` hashes the leaf on the `in` -- the membership twin of the
    `.get()` case above."""
    from webapp.backend import summary
    out = summary.summarize({"devices": {"h": {}}, "migration_readiness": [{"group": "G", "readiness": bad}]})
    assert isinstance(out, dict)


@pytest.mark.parametrize("bad", UNHASHABLE, ids=IDS)
def test_cutover_wave_remediation_and_validation_tolerate_unhashable_severity(bad):
    """The two per-wave roll-ups sort by `_SEV_RANK.get(severity)` on rows read straight out of the
    stored snapshot's remediation_plan / validation_plan -- the same hash, two more sites, both on
    /cutover and (through build_plan) /executions."""
    from webapp.backend import cutover
    plan = cutover.build_plan({
        "devices": {"h": {}},
        "wave_sequencing": [{"group": "Group 1", "switches": ["h"]}],
        "remediation_plan": {"by_device": {"h": [{"severity": bad, "title": "t", "category": "c"}]}},
        "validation_plan": {"by_wave": {"Group 1": [{"severity": bad, "check": "c", "command": "show x"}]}},
    })
    assert isinstance(plan, dict)


@pytest.mark.parametrize("bad", [INF, -INF, float("nan"), BIG, True, "x", {"k": 1}, [1]],
                         ids=["inf", "-inf", "nan", "bigint", "True", "str", "dict", "list"])
def test_stored_snapshot_numeric_leaves_never_500_a_read_route(bad):
    """The class-B (numeric) half on the webapp side: `json.loads` accepts the bare `Infinity`/`NaN`
    and an unbounded-precision int, so a stored snapshot can hold either in any count field. Every
    read projection must coerce fail-soft rather than raise."""
    from webapp.backend import cutover, summary
    snap = {"devices": {"h": {}},
            "failure_impact": [{"host": "h", "severity": "High", "stranded": bad, "vlans_impacted": bad}],
            "health_scores": [{"switch": "h", "band": "Good", "score": bad}],
            "migration_readiness": [{"group": "G", "readiness": "READY", "n_fail": bad}]}
    assert isinstance(summary.summarize(snap), dict)
    assert isinstance(cutover.build_plan(snap), dict)


def test_mixed_type_labels_do_not_break_a_read_route():
    """Class C2 on the webapp side -- no poison at all, just two JSON-legal rows whose `switch` is a
    number on one and a string on the other."""
    from webapp.backend import cutover, summary
    snap = {"devices": {"h": {}},
            "health_scores": [{"switch": 10, "band": "Good"}, {"switch": "h", "band": "Poor"}],
            "failure_impact": [{"host": 10, "severity": "High"}, {"host": "h", "severity": "Low"}]}
    assert isinstance(summary.summarize(snap), dict)
    assert isinstance(cutover.build_plan(snap), dict)


def test_hkey_is_inert_on_well_formed_labels():
    """The guard must not change the rank, order or identity of any real label."""
    from webapp.backend.cutover import _hkey as ck
    from webapp.backend.summary import _hkey as sk
    for h in (ck, sk):
        for v in ("Critical", "High", "", None, 0, 3.5, True, ("a", "b")):
            assert h(v) is v or h(v) == v
