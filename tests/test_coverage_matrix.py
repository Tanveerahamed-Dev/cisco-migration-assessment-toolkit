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


def test_not_collected_device_is_not_silently_dropped():
    """[PR #279] A device the collection NEVER reached (unreachable / auth-fail) is ABSENT from
    snap['devices'] (that map is built only from hosts that collected) but IS present in
    collection_completeness as 'not collected'. The matrix joined on snap['devices'].keys(), so such a
    device emitted ZERO rows and vanished -- reading as fully covered, the exact false-health the module
    exists to prevent (on the AJ fleet: all 50 of 303/253 not-collected devices would disappear). It must
    instead appear as an explicit blind-spot on EVERY base axis, and must NOT read 'covered' on
    capture/parse by mere absence of findings (a never-collected host was never captured or parsed either)."""
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
    for axis in ("collection", "capture", "parse"):
        assert ("sw2", axis) in by, f"not-collected sw2 vanished from the {axis} axis"
        assert by[("sw2", axis)]["state"] == "not_collected", f"sw2 must abstain on {axis}, not fake-cover"
        assert by[("sw2", axis)]["is_abstention"]
    assert cm["summary"]["n_devices"] == 2                            # the inventory universe now counts sw2
    assert "sw2" not in {r["device"] for r in cm["rows"] if r["state"] == "covered"}
    assert by[("sw1", "collection")]["state"] == "partial"           # control: sw1 keeps its REAL verdicts
    assert by[("sw1", "capture")]["state"] == "covered"
    assert by[("sw1", "parse")]["state"] == "covered"


def test_struct_keyed_observed_arch_axis_emits_no_struct_field_device_rows():
    """[PR #282] Coverage-honest join against the inventory. A JSON controller axis is published
    `{host: {faults, nodes, ...}}`, so architecture_coverage's `hosts` are controller hostnames. But if a
    malformed / bare struct-keyed axis (`{faults:.., nodes:..}`) ever reached the matrix, `hosts` would be
    the axis's STRUCTURAL FIELDS -- leaking fake device rows (device='faults' / 'nodes'), all 'covered',
    into by_device and the covered count. A struct key is NOT a device: no such row may appear; the observed
    class collapses to ONE '(fleet)' covered row (the axis WAS observed -- coverage != health)."""
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
    """[PR #282] The struct-key guard must NOT over-collapse the host-keyed norm: an observed axis whose
    hosts ARE inventory devices (every ssh axis, and a controller axis attributed to a collected host --
    e.g. the golden's aci under 'core2') still emits one covered row per REAL device."""
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
