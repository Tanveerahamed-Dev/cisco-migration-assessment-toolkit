"""[audit-5 totality-crash batch] Malformed / hostile snapshot sections (a truthy non-list, or a non-dict
ELEMENT inside an otherwise valid list) must DEGRADE, never raise -- several of these paths are reachable from
the UNAUTHENTICATED webapp snapshot-upload / deliverable routes, where a raw exception escapes as an HTTP 500.
Each test plants a non-dict element in a section whose per-row `.get()` previously crashed."""


def test_compute_design_blueprint_tolerates_nondict_section_elements():
    """[#0/#5] _signals + _role_counts iterate _as_list(section) and call .get() directly on each element, so a
    bare string / int / None ROW in l3_forwarding / health_scores / overlay / copp / fhrp_detail crashed the
    unguarded /design + /architecture_coverage endpoints (AttributeError 'str' object has no attribute 'get')."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    hostile = {
        "devices": {"c": {}},
        "l3_forwarding": ["c v10 single-gateway", None, 7],          # proven repro: string rows
        "health_scores": ["notadict", None, {"role": "core"}],       # _role_counts row
        "overlay": {"h": {"nve_peers": ["x", None], "evpn_neighbors": [1], "nve_vni": [None]}},
        "copp": {"h": ["str", None, {"class": "x", "drops": 5}]},
        "fhrp_detail": {"h": ["str", None]},
    }
    bp = compute_design_blueprint(hostile, {})                       # must NOT raise
    assert isinstance(bp, dict)


def test_compute_multicast_intelligence_tolerates_nondict_querier():
    """[#9] the igmp_queriers comprehension (analyze.py) calls q.get() with no dict-guard, unlike the
    classified_groups loop right above it -- a None / non-dict querier raised AttributeError instead of degrading."""
    from cisco_toolkit import analyze
    out = analyze.compute_multicast_intelligence(
        {"multicast": {"classified_groups": [], "igmp_queriers": [None, "x", {"vlan": "10"}]}}, None)
    assert isinstance(out, dict)


def test_lifecycle_software_risk_tolerate_nonstring_model_version():
    """[#10/#11] compute_lifecycle_risk / compute_software_risk promise 'tolerant / never raises', but call
    .strip() on a raw model/sw_version BEFORE delegating to the str-guarding eoldb.lifecycle_for, so a non-string
    (an int from a malformed snapshot) raised AttributeError."""
    from cisco_toolkit import analyze
    assert analyze.compute_lifecycle_risk({"h": {"model": 12345, "sw_version": 9}}) is not None
    assert analyze.compute_software_risk(
        devices={"H": {"model": 1, "sw_version": 2}}, platforms={"H": {"platform": "nxos"}}) is not None


def test_load_devices_clean_error_on_nondict_entry(tmp_path):
    """[#13/#14] load_devices iterated `for d in data: if alias in d`, assuming every list element is a dict; a
    devices.json that is a list with a bare int / null element raised a cryptic TypeError instead of the clean
    ValueError the function raises for every other malformed-input case."""
    import importlib.util
    import json
    import pytest
    spec = importlib.util.spec_from_file_location("cp_load_devices", "COLLECT_PARSE_V3_23_0.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    p = tmp_path / "devices.json"
    p.write_text(json.dumps([{"ip": "1.1.1.1", "hostname": "a", "username": "u"}, 42, None]))
    with pytest.raises(ValueError):
        m.load_devices(str(p))


def test_compare_diff_tolerates_nondict_device_interface_sections(tmp_path):
    """[#7/#8] --compare path: compute_snapshot_delta used `... or {}` (guards only FALSY, not a truthy non-dict
    list) and write_diff_workbook used `.get(k, {})` (returns None for a present-but-null key), so a snapshot
    whose devices/interfaces section is a list or null crashed with AttributeError / TypeError."""
    from cisco_toolkit import html
    # #7: a truthy non-dict (list) section -> compute_snapshot_delta must degrade, not raise
    d = html.compute_snapshot_delta({"devices": {}, "interfaces": [1, 2]}, {"devices": [3], "interfaces": {}})
    assert isinstance(d, dict) and "verdict" in d
    # #8: present-but-null sections -> write_diff_workbook must not raise
    out = str(tmp_path / "audit5_diff.xlsx")
    html.write_diff_workbook({"devices": None, "interfaces": None, "health_scores": [], "punchlist": []},
                             {"devices": None, "interfaces": None, "health_scores": [], "punchlist": []}, out)
    assert __import__("os").path.exists(out)
