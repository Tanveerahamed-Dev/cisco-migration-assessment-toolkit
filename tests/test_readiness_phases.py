"""Migration-readiness checklist is mapped to recognized runbook phases and
carries the three audit checks (dependency mapping / baseline capture /
rollback). The audit checks are additive: they must never flip a group's
READY / CAUTION / NOT READY verdict on offline data."""


def _dep(**over):
    """Full dependency-map skeleton with empty defaults; override per test
    (mirrors the helper in test_compute.py)."""
    d = {
        "single_fiber": set(), "uplink_ports": set(), "sole_gw": {},
        "access_by_vlan": {}, "articulation": set(), "fhrp_vlans": set(),
        "tracked_down": set(), "errored_up": set(), "halfdup_up": set(),
        "single_member_pc": set(), "errdis": set(), "gw_switches": set(),
        "orphan": set(), "model": {"hosts": set()},
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Phase mapping + presence of the three audit checks
# --------------------------------------------------------------------------- #
def test_every_check_has_a_phase(cp):
    move_groups = [{"switches": ["a"], "endpoints": 1}]
    health = [{"switch": "a", "band": "Good"}]
    dep = _dep(model={"hosts": {"a"}})
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], dep)
    checks = out[0]["checks"]
    assert checks, "no checks emitted"
    for chk in checks:
        assert chk.get("phase"), f"check {chk['check']!r} is missing a phase"
        assert chk["phase"] in {
            "Inventory", "Baseline capture", "Dependency mapping",
            "Pilot/cutover", "Rollback",
        }, f"check {chk['check']!r} has unrecognized phase {chk['phase']!r}"


def test_audit_checks_present(cp):
    move_groups = [{"switches": ["a"], "endpoints": 1}]
    health = [{"switch": "a", "band": "Good"}]
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [],
                                         _dep(model={"hosts": {"a"}}))
    by_name = {c["check"]: c for c in out[0]["checks"]}
    assert "Dependency mapping complete" in by_name
    assert by_name["Dependency mapping complete"]["phase"] == "Dependency mapping"
    assert "Baseline capture" in by_name
    assert by_name["Baseline capture"]["phase"] == "Baseline capture"
    assert "Rollback plan documented" in by_name
    assert by_name["Rollback plan documented"]["phase"] == "Rollback"


def test_rollback_uses_info_status(cp):
    """Rollback has no offline signal: it must use status 'info' so it can never
    flip the READY / CAUTION / NOT READY verdict or the warn/fail counts."""
    move_groups = [{"switches": ["a"], "endpoints": 0}]
    health = [{"switch": "a", "band": "Excellent"}]
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [],
                                         _dep(model={"hosts": {"a"}}))
    rb = next(c for c in out[0]["checks"] if c["check"] == "Rollback plan documented")
    assert rb["status"] == "info"
    # an otherwise clean group stays READY despite the 'info' rollback check
    assert out[0]["readiness"] == "READY"
    assert out[0]["n_fail"] == 0 and out[0]["n_warn"] == 0


def test_audit_checks_pass_on_collected_data(cp):
    """When topology and physical counters are present for the group's switches,
    the data-grounded audit checks evaluate to 'pass' (no cry-wolf)."""
    move_groups = [{"switches": ["a"], "endpoints": 0}]
    health = [{"switch": "a", "band": "Excellent"}]
    physical_health = [{"switch": "a", "port": "Gi0/1", "risk": ""}]
    out = cp.compute_migration_readiness({}, move_groups, health, physical_health,
                                         [], [], [], _dep(model={"hosts": {"a"}}))
    by_name = {c["check"]: c for c in out[0]["checks"]}
    assert by_name["Dependency mapping complete"]["status"] == "pass"
    assert by_name["Baseline capture"]["status"] == "pass"
    assert out[0]["readiness"] == "READY"
    assert out[0]["n_warn"] == 0


def test_audit_checks_never_flip_verdict_when_data_absent(cp):
    """No topology / counter evidence at all -> the audit checks must not cry wolf (the verdict is
    untouched, which is what this test's name has always meant) AND must not claim coverage.

    This test used to assert `status == "pass"` for both checks. That was the ONLY place in the repo
    blessing the R4-1 fabrication: with no evidence at all, `gset - topo_hosts` over an empty set is
    empty, so "nothing is missing" rendered as "topology/dependency map covers all group switches"
    and the group was published READY. Both halves are now pinned separately, because they are
    different promises and only one of them was ever in doubt:

      * the no-cry-wolf contract (verdict, n_warn, n_fail) — unchanged, still asserted below;
      * the coverage claim — must abstain, never assert.

    Whether a wholly unassessed axis should ALSO downgrade READY is a separate design decision and is
    deliberately NOT taken here; if it is ever taken, the verdict assertions below are what change.
    """
    move_groups = [{"switches": ["a"], "endpoints": 0}]
    health = [{"switch": "a", "band": "Excellent"}]
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], _dep())
    by_name = {c["check"]: c for c in out[0]["checks"]}
    for name in ("Dependency mapping complete", "Baseline capture"):
        c = by_name[name]
        assert c["status"] != "pass", \
            f"{name!r} reports PASS with no evidence collected at all: {c['note']!r}"
        assert "NOT ASSESSABLE" in c["note"], f"{name!r} does not disclose that it could not assess"
        flat = " ".join(c["note"].split())          # prose: a re-wrap must not un-pin this
        assert "covers all group switches" not in flat
        assert "captured for all group switches" not in flat
    # the no-cry-wolf contract this test is named for — an unassessed axis is not a warning
    assert out[0]["readiness"] == "READY"
    assert out[0]["n_warn"] == 0 and out[0]["n_fail"] == 0
