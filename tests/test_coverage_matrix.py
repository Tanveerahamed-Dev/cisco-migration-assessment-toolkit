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


def test_struct_keyed_observed_arch_axis_emits_no_struct_field_device_rows():
    """PR #277 adversarial follow-up (companion to PR #279): coverage-honest join against the inventory.
    A JSON controller axis is published `{host: {faults, nodes, ...}}`, so architecture_coverage's `hosts`
    are controller hostnames. But if a malformed / bare struct-keyed axis (`{faults:.., nodes:..}`) ever
    reached the matrix, `hosts` would be the axis's STRUCTURAL FIELDS -- leaking fake device rows
    (device='faults' / device='nodes'), all 'covered', into by_device and the covered count. A struct key
    is NOT a device: no such row may appear; the observed class collapses to ONE '(fleet)' covered row
    (the axis WAS observed -- coverage != health)."""
    struct_keys = ["devices", "fabric_health", "faults", "nodes", "summary"]   # none is an inventory member
    snap = {"devices": {"sw1": {}, "sw2": {}},
            "architecture_coverage": {"classes": [
                {"key": "aci", "label": "Cisco ACI (APIC fabric)", "observed": True, "status": "finding",
                 "findings": ["aci-critical-fault-raised"], "hosts": struct_keys},
            ]}}
    cm = compute_coverage_matrix(snap)
    aci_rows = [r for r in cm["rows"] if r["axis"] == "aci"]
    leaked = sorted(set(struct_keys) & {r["device"] for r in aci_rows})
    assert not leaked, f"struct-field(s) leaked as device rows: {leaked}"
    assert not (set(struct_keys) & set(cm["by_device"])), "struct fields polluted by_device"
    assert len(aci_rows) == 1 and aci_rows[0]["device"] == "(fleet)"
    assert aci_rows[0]["state"] == "covered" and aci_rows[0]["is_abstention"] is False


def test_host_keyed_observed_arch_axis_still_emits_per_real_device_rows():
    """The struct-key guard must NOT over-collapse the host-keyed norm: an observed axis whose hosts ARE
    inventory devices (every ssh axis, and a controller axis attributed to a collected host -- e.g. the
    golden's aci under 'core2') still emits one covered row per REAL device."""
    snap = {"devices": {"core1": {}, "core2": {}},
            "architecture_coverage": {"classes": [
                {"key": "aci", "label": "Cisco ACI", "observed": True, "status": "finding",
                 "findings": ["aci-critical-fault-raised"], "hosts": ["core2"]},
                {"key": "fhrp_detail", "label": "FHRP", "observed": True, "status": "clean",
                 "hosts": ["core1", "core2"]},
            ]}}
    cm = compute_coverage_matrix(snap)
    aci = [r for r in cm["rows"] if r["axis"] == "aci"]
    assert len(aci) == 1 and aci[0]["device"] == "core2" and aci[0]["state"] == "covered"
    assert sorted(r["device"] for r in cm["rows"] if r["axis"] == "fhrp_detail") == ["core1", "core2"]


def test_deterministic_and_degrades_on_empty():
    snap = {"devices": {"b": {}, "a": {}}, "collection_completeness": {"devices": []},
            "capture_integrity": {"findings": []}, "parse_yield": {"events": []}}
    assert compute_coverage_matrix(snap) == compute_coverage_matrix(snap)         # deterministic
    empty = compute_coverage_matrix({})
    assert empty["rows"] == [] and empty["summary"]["n_rows"] == 0                # fail-soft
