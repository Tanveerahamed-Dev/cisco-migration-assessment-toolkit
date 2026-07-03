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


def test_deterministic_and_degrades_on_empty():
    snap = {"devices": {"b": {}, "a": {}}, "collection_completeness": {"devices": []},
            "capture_integrity": {"findings": []}, "parse_yield": {"events": []}}
    assert compute_coverage_matrix(snap) == compute_coverage_matrix(snap)         # deterministic
    empty = compute_coverage_matrix({})
    assert empty["rows"] == [] and empty["summary"]["n_rows"] == 0                # fail-soft
