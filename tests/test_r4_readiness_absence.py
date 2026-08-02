"""A move group must never be graded off evidence that was never collected (R4-1).

`compute_migration_readiness` derives two of its runbook audit checks as a set difference:

    missing_topo = sorted(gset - topo_hosts) if topo_hosts else []

When the evidence set is WHOLLY EMPTY that difference is empty, so "nothing is missing" became
`pass` with an affirmative note. With no topology and no interface counters collected at all, a
group was published as::

    PASS | Dependency mapping complete: topology/dependency map covers all group switches
    PASS | Baseline capture:            interface/physical counters captured for all group switches
    VERDICT: READY   n_warn: 0

Both sentences assert COVERAGE of evidence that does not exist, on the verdict a human schedules a
production cutover from. `snap['migration_readiness']` feeds the runbook, deck and design
deliverables. CLAUDE.md guardrail 3: "not observed" never silently becomes "healthy".

The same function's `Device health floor` check ~12 lines earlier already handled the identical
no-evidence case correctly ("not assessable"), so the right shape was present in the same function
and simply not applied to these two siblings.

Found by auditing a TEST rather than the code: the only test covering this behaviour
(tests/test_readiness_phases.py) pins the fall-back as DESIRED — "the audit checks fall back to pass
rather than crying wolf" — and no ADR accepts the trade. That is why a scanner could never have
surfaced it.
"""

from __future__ import annotations

from cisco_toolkit.analyze import compute_migration_readiness

_AUDIT = ("Dependency mapping complete", "Baseline capture")


def _empty_dep_map(topo_hosts=()):
    """The shape compute_migration_readiness indexes, carrying no findings.

    The topology evidence is read from ``dep_map["model"]["hosts"]`` (analyze.py:2050-2051) — NOT
    from a "topology" key. Naming it wrongly here would leave `topo_hosts` empty in every case, so
    the two control tests below would exercise the abstention branch too and this file would pin
    only the branch it was written to change.
    """
    return {"single_fiber": [], "errdis": [], "halfdup_up": [], "orphan": [],
            "sole_gw": {}, "access_by_vlan": {},
            "model": {"hosts": list(topo_hosts)}}


def _run(all_interfaces, physical_health, dep_map=None):
    out = compute_migration_readiness(
        all_interfaces,
        [{"switches": ["a"], "endpoints": 0}],
        [{"switch": "a", "band": "Excellent"}],
        physical_health, [], [], [],
        dep_map if dep_map is not None else _empty_dep_map(),
    )
    groups = out.get("groups") if isinstance(out, dict) else out
    return {c["check"]: c for c in groups[0]["checks"]}, groups[0]


def test_wholly_uncollected_axes_are_not_published_as_covered():
    """The defect: an affirmative coverage claim over an empty evidence set."""
    checks, group = _run({}, [])

    for name in _AUDIT:
        c = checks[name]
        assert c["status"] != "pass", (
            f"{name!r} reports PASS with no evidence collected at all: {c['note']!r}")
        assert "NOT ASSESSABLE" in c["note"], f"{name!r} does not say it could not be assessed"
        # The specific sentences that were fabricated. Whitespace-normalised, because these are
        # prose and a re-wrap must not silently un-pin them.
        flat = " ".join(c["note"].split())
        assert "covers all group switches" not in flat, f"{name!r} still claims topology coverage"
        assert "captured for all group switches" not in flat, f"{name!r} still claims a baseline"

    # The no-cry-wolf contract is unchanged: an unassessable axis must not manufacture a warning
    # either. Whether absence should ALSO downgrade READY is a separate design decision.
    assert group["n_warn"] == 0, "an unassessed axis must not be turned into a false warning"


def test_a_real_measurement_still_passes():
    """Refute the fix: evidence present and complete must still read PASS, with its original note —
    otherwise this is a blanket demotion rather than an abstention."""
    checks, _ = _run({"a": {"Gi1/0/1": {}}}, [{"switch": "a"}],
                     dep_map=_empty_dep_map(topo_hosts=["a"]))
    for name in _AUDIT:
        assert checks[name]["status"] == "pass", \
            f"{name!r} regressed to {checks[name]['status']!r} on complete evidence"
        assert "NOT ASSESSABLE" not in checks[name]["note"]


def test_partial_evidence_still_warns_and_names_the_gap():
    """The middle case must be untouched: some hosts measured, this group's not -> warn, naming
    them. If this regressed to the abstention the fix would be hiding real gaps."""
    checks, _ = _run({"other": {"Gi1/0/1": {}}}, [{"switch": "other"}],
                     dep_map=_empty_dep_map(topo_hosts=["other"]))
    for name in _AUDIT:
        c = checks[name]
        assert c["status"] == "warn", f"{name!r} is {c['status']!r}, expected warn for a real gap"
        assert "a" in c["note"], f"{name!r} does not name the uncovered host: {c['note']!r}"
        assert "NOT ASSESSABLE" not in c["note"], \
            f"{name!r} abstained where it had evidence and should have warned"
