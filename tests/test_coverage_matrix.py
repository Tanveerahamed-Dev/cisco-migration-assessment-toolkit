"""Plan-A #5: the composed coverage matrix. Pins that it PROJECTS the four coverage sources
(recomputes no device state), is coverage-honest (abstention explicit, never a fake 'covered'),
and is deterministic."""
import json
import os

import pytest

from cisco_toolkit.coverage_matrix import compute_coverage_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
RICH = os.path.join(HERE, "..", "webapp", "sample_data", "sample_fleet.snapshot.json")


@pytest.fixture(scope="module")
def rich():
    if not os.path.exists(RICH):
        pytest.skip("rich sample absent")
    with open(RICH, encoding="utf-8") as f:
        return json.load(f)


def test_structure_and_summary_consistency(rich):
    cm = compute_coverage_matrix(rich)
    assert set(cm) == {"rows", "by_device", "summary"}
    s = cm["summary"]
    assert s["n_rows"] == len(cm["rows"])
    assert s["n_abstained"] == sum(1 for r in cm["rows"] if r["is_abstention"])
    assert s["n_covered"] == s["n_rows"] - s["n_abstained"]
    assert sum(s["by_state"].values()) == s["n_rows"]
    for r in cm["rows"]:
        assert {"device", "axis", "dimension", "state", "verdict_source", "is_abstention"} <= set(r)
        assert r["is_abstention"] == (r["state"] != "covered")     # abstention is exactly not-covered


def test_every_inventory_device_has_the_three_core_axes(rich):
    cm = compute_coverage_matrix(rich)
    devices = set(rich.get("devices", {}))
    for d in devices:
        axes = {r["axis"] for r in cm["rows"] if r["device"] == d}
        assert {"collection", "capture", "parse"} <= axes, f"{d} missing a core coverage axis"
    assert cm["summary"]["n_devices"] == len(devices)


def test_no_fake_covered_on_collection(rich):
    """A device flagged not_collected/partial in collection_completeness must NOT read 'covered'."""
    cc = {d.get("host"): str(d.get("status", "")).lower()
          for d in (rich.get("collection_completeness") or {}).get("devices", []) if isinstance(d, dict)}
    for r in compute_coverage_matrix(rich)["rows"]:
        if r["axis"] == "collection" and cc.get(r["device"]) and "complete" not in cc[r["device"]]:
            assert r["state"] != "covered", f"{r['device']} is a collection blind-spot but reads covered"


def test_capture_findings_become_unverified_abstentions(rich):
    ci_hosts = {f.get("host") for f in (rich.get("capture_integrity") or {}).get("findings", [])
                if isinstance(f, dict) and f.get("host")}
    cap = {r["device"]: r for r in compute_coverage_matrix(rich)["rows"] if r["axis"] == "capture"}
    for h in ci_hosts & set(rich.get("devices", {})):
        assert cap[h]["state"] == "unverified" and cap[h]["is_abstention"]


def test_not_observed_arch_classes_are_fleet_abstentions():
    snap = {"devices": {"sw1": {}},
            "architecture_coverage": {"classes": [
                {"key": "lisp", "label": "LISP", "observed": False, "hosts": []},
                {"key": "fhrp_detail", "label": "FHRP", "observed": True, "status": "clean", "hosts": ["sw1"]},
            ]}}
    cm = compute_coverage_matrix(snap)
    lisp = [r for r in cm["rows"] if r["axis"] == "lisp"]
    assert len(lisp) == 1 and lisp[0]["device"] == "(fleet)" and lisp[0]["state"] == "not_observed"
    fhrp = [r for r in cm["rows"] if r["axis"] == "fhrp_detail"]
    assert len(fhrp) == 1 and fhrp[0]["device"] == "sw1" and fhrp[0]["state"] == "covered"


def test_not_collected_device_is_not_silently_dropped():
    """[review PR#277 — coverage-honesty inversion] A device the collection NEVER reached
    (unreachable / auth-fail) is ABSENT from snap['devices'] (that map is built only from hosts
    that collected) but IS present in collection_completeness as 'not collected'. The matrix joined
    on snap['devices'].keys(), so such a device emitted ZERO rows and vanished — reading as fully
    covered, the exact false-health the module exists to prevent (on the AJ fleet: all 50 of
    303/253 not-collected devices would disappear). It must instead appear as an explicit blind-spot
    on EVERY base axis, and must NOT read 'covered' on capture/parse by mere absence of findings
    (a never-collected host was never captured or parsed either). The synthetic golden/sample carry
    zero blind spots, so ONLY this fixture exercises the guarantee."""
    snap = {
        "devices": {"sw1": {}},                                      # sw1 is the only host that collected
        "collection_completeness": {"devices": [
            {"host": "sw1", "status": "partial", "missing": ["show cdp neighbors"]},
            {"host": "sw2", "status": "not collected", "missing": ["<all commands>"]},  # never reached
        ]},
        "capture_integrity": {"findings": []},
        "parse_yield": {"events": []},
    }
    cm = compute_coverage_matrix(snap)
    by = {(r["device"], r["axis"]): r for r in cm["rows"]}
    # sw2 (never collected) is present on all three base axes, every one an explicit abstention.
    for axis in ("collection", "capture", "parse"):
        assert ("sw2", axis) in by, f"not-collected sw2 vanished from the {axis} axis"
        assert by[("sw2", axis)]["state"] == "not_collected", f"sw2 must abstain on {axis}, not fake-cover"
        assert by[("sw2", axis)]["is_abstention"]
    # the inventory universe now counts sw2 (n_devices was under-reporting the collected subset)
    assert cm["summary"]["n_devices"] == 2
    # a total blind spot is never a 'covered' device on any axis
    assert "sw2" not in {r["device"] for r in cm["rows"] if r["state"] == "covered"}
    # control — sw1 (partially collected) still reports its REAL per-axis verdicts, unchanged:
    assert by[("sw1", "collection")]["state"] == "partial"
    assert by[("sw1", "capture")]["state"] == "covered"     # collected + no capture finding => genuinely covered
    assert by[("sw1", "parse")]["state"] == "covered"


def test_deterministic_and_degrades_on_empty():
    snap = {"devices": {"b": {}, "a": {}}, "collection_completeness": {"devices": []},
            "capture_integrity": {"findings": []}, "parse_yield": {"events": []}}
    assert compute_coverage_matrix(snap) == compute_coverage_matrix(snap)         # deterministic
    empty = compute_coverage_matrix({})
    assert empty["rows"] == [] and empty["summary"]["n_rows"] == 0                # fail-soft
