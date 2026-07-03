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


def test_no_fake_covered_on_collection():
    """A device flagged not_collected/partial in collection_completeness must NOT read 'covered'. Synthetic
    (NOT the rich sample, which happens to carry zero blind-spots -> the old rich-scan asserted nothing and
    silently skipped when the sample was absent): pin the false-health guard on a real not_collected + partial
    device so the branch is GUARANTEED to exercise on every run."""
    snap = {"devices": {"good": {}, "blind": {}, "half": {}},
            "collection_completeness": {"summary": {}, "devices": [
                {"host": "blind", "status": "not collected", "missing": ["show version", "show run"]},
                {"host": "half", "status": "partial", "missing": ["show cdp neighbors detail"]}]}}
    col = {r["device"]: r for r in compute_coverage_matrix(snap)["rows"] if r["axis"] == "collection"}
    assert col["blind"]["state"] == "not_collected" and col["blind"]["is_abstention"]   # blind-spot != covered
    assert col["half"]["state"] == "partial" and col["half"]["is_abstention"]            # partial != covered
    assert col["good"]["state"] == "covered"                                             # non-blind-spot IS covered


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


def test_fleet_pseudo_device_not_in_by_device():
    """The '(fleet)' not-observed arch rows are fleet-level, not a device -- they must NOT pollute by_device
    (which is a per-DEVICE view) or n_devices, else a consumer iterating by_device renders a phantom host."""
    snap = {"devices": {"sw1": {}},
            "architecture_coverage": {"classes": [
                {"key": "lisp", "label": "LISP", "observed": False, "hosts": []}]}}
    cm = compute_coverage_matrix(snap)
    assert any(r["device"] == "(fleet)" for r in cm["rows"])          # the fleet ROW still exists
    assert "(fleet)" not in cm["by_device"]                          # but it is not a device
    assert set(cm["by_device"]) == {"sw1"}
    assert cm["summary"]["n_devices"] == 1


def test_n_axes_counts_dimensions_not_architecture_keys():
    """n_axes must count the coverage DIMENSIONS (collection/capture/parse/architecture), not inflate with
    every architecture key -- otherwise it reports ~32 on a real fleet and misleads any 'axes assessed' read."""
    snap = {"devices": {"sw1": {}},
            "architecture_coverage": {"classes": [
                {"key": "lisp", "label": "LISP", "observed": False, "hosts": []},
                {"key": "cts", "label": "CTS", "observed": False, "hosts": []},
                {"key": "fhrp_detail", "label": "FHRP", "observed": True, "status": "clean", "hosts": ["sw1"]}]}}
    cm = compute_coverage_matrix(snap)
    dims = {r["dimension"] for r in cm["rows"]}
    assert cm["summary"]["n_axes"] == len(dims)                       # dimensions, not arch keys
    assert cm["summary"]["n_axes"] <= 4                               # collection/capture/parse/architecture
    # the 3 distinct arch keys must NOT inflate n_axes past the 4 dimensions
    assert cm["summary"]["n_axes"] == 4


def test_parse_axis_attributes_fs_sanitized_hostname():
    """parse_yield events attribute the device by its on-disk collection-dir basename = safe_fs_name(hostname),
    but the join universe is the RAW hostname. A host whose name carries an FS-reserved char must still be
    attributed its suspect parse event (never silently read 'covered' -- a coverage-honesty false-health)."""
    from cisco_toolkit.textutils import safe_fs_name
    host = "core-sw:1"                                                # ':' -> '_' under safe_fs_name
    assert safe_fs_name(host) != host                                # precondition: the name IS sanitized
    snap = {"devices": {host: {}},
            "parse_yield": {"events": [
                {"parser": "parse_ip_routes", "device": safe_fs_name(host),
                 "cmd": "show ip route", "error": True}]}}
    cm = compute_coverage_matrix(snap)
    parse_rows = [r for r in cm["rows"] if r["axis"] == "parse"]
    assert len(parse_rows) == 1 and parse_rows[0]["device"] == host
    assert parse_rows[0]["state"] == "unparsed" and parse_rows[0]["is_abstention"]
