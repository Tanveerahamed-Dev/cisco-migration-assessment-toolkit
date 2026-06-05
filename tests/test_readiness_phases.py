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
    """No topology / counter evidence at all -> the audit checks fall back to
    'pass' rather than crying wolf, so a clean group stays READY."""
    move_groups = [{"switches": ["a"], "endpoints": 0}]
    health = [{"switch": "a", "band": "Excellent"}]
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], _dep())
    by_name = {c["check"]: c for c in out[0]["checks"]}
    assert by_name["Dependency mapping complete"]["status"] == "pass"
    assert by_name["Baseline capture"]["status"] == "pass"
    assert out[0]["readiness"] == "READY"
    assert out[0]["n_warn"] == 0 and out[0]["n_fail"] == 0
