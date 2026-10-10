"""W12-B independently chosen expectations for ephemeral device counts and guarded VLAN waves.

These synthetic snapshots exercise admission, not field qualification. No stored sample,
golden or persisted engine section is modified. Real VLAN and punch-list producers supply
the positive integration records; negative edits preserve contradictory evidence.
"""
from copy import deepcopy
from dataclasses import asdict

import pytest
from jsonschema import Draft202012Validator, ValidationError

from cisco_toolkit import analyze, parse, ssot
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.model import InterfaceData

PUB = "published"
CBE = "collected_but_empty"
NC = "not_collected"
UV = "unverified"
AU = "analysis_unavailable"
HOSTS = ("edgeA", "edgeB", "empty")
SEVERITIES = ("Critical", "High", "Medium", "Low", "Info")
ZERO = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}


def _snapshot(rows=None):
    # Every punch-list input is present, so absent phase evidence cannot prove a zero.
    snap = {section: [] for section in uip.PUNCHLIST_INPUTS}
    snap.update({
        "schema": "collect_parse_snapshot/1",
        "devices": {host: {"hostname": host} for host in HOSTS},
        "interfaces": {
            host: {"Gi1/0/1": asdict(InterfaceData(port="Gi1/0/1", switchport_mode="Access", vlan="10"))}
            for host in HOSTS
        },
        "punchlist": deepcopy(rows if rows is not None else []),
        "security": {host: parse.parse_security("hostname " + host + "\n") for host in HOSTS},
        "config_hygiene": {},
        "software_risk": {"per_device": [{"host": host, "config_assessable": True} for host in HOSTS]},
        "qos_audit": {"per_device": []},
        "syslog_intelligence": {"per_device": []},
        "platform_health": {"per_device": []},
        "device_dossiers": {"per_device": []},
        "protocol_assessability": {},
        "vtp_safety_baseline": {},
        "ipv6_routing_adjacency_baseline": {},
        "collection_completeness": {
            "devices": [], "summary": {"inventory": len(HOSTS), "collected": len(HOSTS)},
        },
        "stp_roots": {},
        "vlan_cutover": [],
    })
    return snap


def _stored_rows():
    # Legacy display fields intentionally absent: they cannot alter severity membership.
    return [
        {"severity": "High", "devices": ["edgeA", "edgeA", "edgeB"]},
        {"severity": "Critical", "devices": ["edgeA"]},
        {"severity": "Info", "devices": ["edgeB"]},
        {"severity": "High", "devices": ["edgeA"]},
        {"severity": "Low", "devices": []},
    ]


def _inventory_rollup(snap, host):
    rows = uip.project_inventory(snap)["devices"]["rows"]["items"]
    selected = [row for row in rows if row["host"] == host]
    assert len(selected) == 1
    return selected[0]["findings"]


def _device_rollup(snap, host):
    return uip.project_device(snap, host)["device"]["findings_rollup"]


def _assert_held(snap, host, state):
    inventory, device = _inventory_rollup(snap, host), _device_rollup(snap, host)
    assert inventory == device
    for fact in inventory.values():
        assert fact["state"] == state
        assert fact["value"] is None
        assert fact["reason"]
    return inventory


def _assert_counts(snap, host, counts, worst):
    inventory, device = _inventory_rollup(snap, host), _device_rollup(snap, host)
    assert inventory == device
    assert inventory["by_severity"]["state"] == PUB
    assert inventory["by_severity"]["value"] == counts
    assert list(inventory["by_severity"]["value"]) == list(SEVERITIES)
    if worst is None:
        assert inventory["worst"]["state"] == CBE
        assert inventory["worst"]["value"] is None
        assert "not a clean bill of health" in inventory["worst"]["reason"]
    else:
        assert inventory["worst"]["state"] == PUB
        assert inventory["worst"]["value"] == worst
    return inventory


def test_stored_rows_dedupe_membership_but_preserve_distinct_and_multi_device_findings():
    snap = _snapshot(_stored_rows())
    a = _assert_counts(snap, "edgeA", {"Critical": 1, "High": 2, "Medium": 0, "Low": 0, "Info": 0}, "Critical")
    b = _assert_counts(snap, "edgeB", {"Critical": 0, "High": 1, "Medium": 0, "Low": 0, "Info": 1}, "High")
    _assert_counts(snap, "empty", ZERO, None)
    for rollup, expected in ((a, {0, 1, 3}), (b, {0, 2})):
        for fact in rollup.values():
            actual = {ref["pointer"] for ref in fact["refs"]
                      if ref["role"] == "witness" and ref["pointer"].startswith("/punchlist/")}
            assert actual == {f"/punchlist/{index}" for index in expected}
    assert "device_findings_scope" in a["by_severity"]["caveats"]


def test_real_punchlist_producer_rows_publish_the_same_independent_device_counts():
    rows = analyze.compute_migration_punchlist(
        cross_layer=[
            {"severity": "Critical", "hosts": ["edgeA", "edgeB"], "title": "shared dependency", "detail": "observed"},
            {"severity": "High", "hosts": ["edgeA"], "title": "separate finding", "detail": "observed"},
            {"severity": "Info", "hosts": ["edgeB"], "title": "context", "detail": "observed"},
        ],
        security={}, config_hygiene={}, physical_health=[], l3_forwarding=[], protocol_health=[],
        stp_findings={}, health_scores=[], move_groups=[],
    )
    snap = _snapshot(rows)
    _assert_counts(snap, "edgeA", {"Critical": 1, "High": 1, "Medium": 0, "Low": 0, "Info": 0}, "Critical")
    _assert_counts(snap, "edgeB", {"Critical": 1, "High": 0, "Medium": 0, "Low": 0, "Info": 1}, "Critical")


def test_assessed_empty_has_measured_zero_counts_and_no_invented_clean_severity():
    _assert_counts(_snapshot(), "edgeA", ZERO, None)


@pytest.mark.parametrize("retained", [False, True])
def test_canonical_false_is_not_collected_even_with_retained_rows_and_positive_qos(retained):
    snap = _snapshot(_stored_rows() if retained else [])
    snap["software_risk"]["per_device"][0]["config_assessable"] = False
    snap["qos_audit"]["per_device"] = [{"host": "edgeA", "assessable": True}]
    _assert_held(snap, "edgeA", NC)


@pytest.mark.parametrize("flag", [None, 1, 0, "true", [], {}])
def test_present_malformed_canonical_flag_never_falls_back_to_positive_qos(flag):
    snap = _snapshot()
    snap["software_risk"]["per_device"][0]["config_assessable"] = flag
    snap["qos_audit"]["per_device"] = [{"host": "edgeA", "assessable": True}]
    _assert_held(snap, "edgeA", UV)


def test_missing_canonical_flag_and_missing_capture_rows_withhold_zero():
    snap = _snapshot()
    del snap["software_risk"]["per_device"][0]["config_assessable"]
    snap["qos_audit"]["per_device"] = [{"host": "edgeA", "assessable": True}]
    _assert_held(snap, "edgeA", UV)
    snap["software_risk"]["per_device"] = []
    snap["qos_audit"]["per_device"] = []
    _assert_held(snap, "edgeA", UV)


@pytest.mark.parametrize("section", ["software_risk", "qos_audit"])
def test_duplicate_exact_capture_rows_withhold_a_partition(section):
    snap = _snapshot()
    if section == "qos_audit":
        snap["software_risk"]["per_device"] = []
        record = {"host": "edgeA", "assessable": True}
    else:
        record = {"host": "edgeA", "config_assessable": True}
    snap[section]["per_device"] = [record, deepcopy(record)]
    _assert_held(snap, "edgeA", UV)


@pytest.mark.parametrize("records", [None, {}, [None], [{}], [{"host": ""}], [{"host": "\ud800"}]])
def test_unreadable_capture_membership_withholds_even_when_a_positive_row_exists(records):
    snap = _snapshot()
    snap["software_risk"]["per_device"] = records
    snap["qos_audit"]["per_device"] = [{"host": "edgeA", "assessable": True}]
    _assert_held(snap, "edgeA", UV)


def test_qos_fallback_is_used_only_when_the_exact_canonical_row_is_absent():
    snap = _snapshot()
    snap["software_risk"]["per_device"] = [{"host": "edgeB", "config_assessable": False}]
    snap["qos_audit"]["per_device"] = [{"host": "edgeA", "assessable": True}]
    _assert_counts(snap, "edgeA", ZERO, None)
    snap["software_risk"]["per_device"].append({"host": "edgeA", "config_assessable": False})
    _assert_held(snap, "edgeA", NC)
    snap["software_risk"]["per_device"][-1]["config_assessable"] = True
    snap["qos_audit"]["per_device"][0]["assessable"] = False
    _assert_counts(snap, "edgeA", ZERO, None)


@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("host", ["edgeA", "ghost"])
def test_existing_and_inventory_only_blind_devices_never_publish_zero(retained, host):
    rows = [{"severity": "High", "devices": [host]}] if retained else []
    snap = _snapshot(rows)
    snap["collection_completeness"]["devices"] = [
        {"host": host, "status": "not collected", "missing": ["interface status"], "data_quality": 0},
    ]
    if host == "ghost":
        snap["collection_completeness"]["summary"]["inventory"] += 1
    held = _assert_held(snap, host, NC)
    assert all({"pointer": "/collection_completeness/devices/0", "role": "witness"} in fact["refs"]
               for fact in held.values())


@pytest.mark.parametrize("retained", [False, True])
def test_configless_device_without_security_assessment_never_publishes_zero(retained):
    snap = _snapshot(_stored_rows() if retained else [])
    snap["software_risk"]["per_device"][0]["config_assessable"] = False
    del snap["security"]["edgeA"]
    _assert_held(snap, "edgeA", NC)


@pytest.mark.parametrize("record", [{}, [], None])
def test_positive_capture_does_not_authorize_zero_over_an_unreadable_security_record(record):
    snap = _snapshot()
    snap["security"]["edgeA"] = record
    _assert_held(snap, "edgeA", UV)


@pytest.mark.parametrize("retained", [False, True])
def test_failed_punchlist_input_remains_unavailable_with_or_without_stored_findings(retained):
    snap = _snapshot(_stored_rows() if retained else [])
    snap["health_scores"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    assert ssot.abstention_reason(snap, "health_scores") == AU
    held = _assert_held(snap, "edgeA", AU)
    assert all({"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"} in fact["refs"]
               for fact in held.values())


@pytest.mark.parametrize("bad_row", [None, {}, {"severity": "Unknown", "devices": ["outside"]},
                                    {"severity": "High", "devices": "edgeA"},
                                    {"severity": "High", "devices": ["edgeA", None]}])
def test_unreadable_tail_invalidates_all_device_rollups_without_partial_counts(bad_row):
    snap = _snapshot(_stored_rows() + [bad_row])
    for host in HOSTS:
        _assert_held(snap, host, UV)


@pytest.mark.parametrize("host,state", [("", NC), ("unknown", NC), (7, UV), (None, UV)])
def test_unknown_or_nontext_device_rollup_has_no_claim_or_fleet_references(host, state):
    snap = _snapshot(_stored_rows())
    rollup = _device_rollup(snap, host)
    for fact in rollup.values():
        assert fact["state"] == state
        assert fact["value"] is None
        assert fact["subject"] is None
        assert fact["refs"] == []


@pytest.mark.parametrize("edit", [
    lambda counts: counts.update(High=1.0), lambda counts: counts.update(High=0.0),
    lambda counts: counts.update(High=True), lambda counts: counts.update(High=-1),
    lambda counts: counts.update(High=2 ** 53), lambda counts: counts.update(Unknown=0),
    lambda counts: counts.pop("Info"), lambda counts: counts.update(High="1"),
])
def test_closed_severity_counts_reject_type_aliases_bounds_and_wrong_keys(edit):
    counts = deepcopy(ZERO)
    edit(counts)
    assert uip._typed(counts, "severity_counts") == (False, None)


def test_fold_cache_is_once_per_context_and_projected_containers_are_independent(monkeypatch):
    snap = _snapshot(_stored_rows())
    frozen = deepcopy(snap)
    calls = []
    owner = uip.compute_device_findings

    def counted(rows, hosts):
        calls.append(tuple(hosts))
        return owner(rows, hosts)

    monkeypatch.setattr(uip, "compute_device_findings", counted)
    inventory = uip.project_inventory(snap)
    assert calls == [tuple(sorted(HOSTS))]
    pages = uip.project_devices(snap, list(HOSTS))
    assert calls == [tuple(sorted(HOSTS)), tuple(sorted(HOSTS))]
    assert snap == frozen
    first = next(row for row in inventory["devices"]["rows"]["items"] if row["host"] == "edgeA")["findings"]
    first["by_severity"]["value"]["High"] = 999
    first["worst"]["value"] = "Low"
    first["by_severity"]["refs"].append({"pointer": "/injected", "role": "witness"})
    assert pages[0]["device"]["findings_rollup"]["by_severity"]["value"]["High"] == 2
    assert pages[0]["device"]["findings_rollup"]["worst"]["value"] == "Critical"
    assert snap == frozen
    fresh = _inventory_rollup(snap, "edgeA")
    assert fresh["by_severity"]["value"]["High"] == 2
    assert all(ref["pointer"] != "/injected" for ref in fresh["by_severity"]["refs"])


def test_new_rollup_and_count_schema_is_closed_and_validates_actual_projected_documents():
    snap = _snapshot(_stored_rows())
    schema = uip.ui_projection_schema()
    Draft202012Validator.check_schema(schema)
    root_validator = Draft202012Validator(schema)
    doc_validator = Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                          "$ref": "#/$defs/DeviceDocument"})
    root_validator.validate(uip.project(snap))
    doc = uip.project_device(snap, "edgeA")
    doc_validator.validate(doc)
    for change in (
        lambda item: item.update(extra=True),
        lambda item: item["by_severity"]["value"].update(Unknown=0),
        lambda item: item["by_severity"]["value"].pop("Info"),
        lambda item: item["by_severity"]["value"].update(High=True),
    ):
        bad = deepcopy(doc)
        change(bad["device"]["findings_rollup"])
        with pytest.raises(ValidationError):
            doc_validator.validate(bad)


def _vlan_snapshot(groups=None):
    interfaces = {
        "edgeA": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", switchport_mode="Access", vlan="010")},
        "edgeB": {"Vlan0010": InterfaceData(port="Vlan0010")},
        "outside": {"Gi1/0/2": InterfaceData(port="Gi1/0/2", switchport_mode="Access", vlan="10")},
    }
    roots = {"stp-only": {"30": {"is_mst": False, "is_root": False,
                                "root_priority": 32798, "root_address": "aaaa.0001.0001"}}}
    if groups is None:
        groups = [{"group": "Later, measured", "switches": ["edgeB"]},
                  {"group": "Pilot", "switches": ["edgeA"]},
                  {"group": "Root", "switches": ["stp-only"]}]
    labels = analyze.move_group_labels(groups)
    sequencing = [{"group": label, "make_before_break": list(group["switches"]),
                   "hard_cutover": [], "homing_unknown": []} for label, group in zip(labels, groups)]
    snap = _snapshot()
    snap["interfaces"] = {host: {port: asdict(record) for port, record in ports.items()}
                          for host, ports in interfaces.items()}
    snap["stp_roots"] = roots
    snap["move_groups"] = deepcopy(groups)
    snap["wave_sequencing"] = sequencing
    snap["vlan_cutover"] = analyze.compute_vlan_cutover_matrix(
        interfaces, roots, move_groups=groups, wave_sequencing=sequencing,
    )
    return snap, interfaces


def _vlan_wave(snap, vlan=10):
    rows = uip.project_inventory(snap)["vlans"]["rows"]["items"]
    matches = [row for row in rows if row["vlan"]["state"] == PUB and row["vlan"]["value"] == vlan]
    # A failed interfaces input withholds vlan itself; the producer's row index still names the source.
    if not matches:
        index = next(index for index, row in enumerate(snap["vlan_cutover"]) if row["vlan"] == vlan)
        matches = [row for row in rows if row["index"] == index]
    assert len(matches) == 1
    return matches[0]["wave"]


def test_real_vlan_producer_and_serialized_capture_share_the_exact_host_universe_and_wave_order():
    snap, interfaces = _vlan_snapshot()
    assert analyze.vlan_cutover_host_index(interfaces, snap["stp_roots"]) == {
        10: {"edgeA", "edgeB", "outside"}, 30: {"stp-only"},
    }
    assert analyze.vlan_cutover_host_index(snap["interfaces"], snap["stp_roots"]) == {
        10: {"edgeA", "edgeB", "outside"}, 30: {"stp-only"},
    }
    fact = _vlan_wave(snap)
    assert (fact["state"], fact["value"]) == (PUB, "Later, measured, Pilot")
    assert _vlan_wave(snap, 30)["value"] == "Root"
    assert "(unscheduled)" not in fact["value"]
    groups = list(reversed(snap["move_groups"]))
    reversed_snap, _interfaces = _vlan_snapshot(groups)
    assert _vlan_wave(reversed_snap)["value"] == "Pilot, Later, measured"


@pytest.mark.parametrize("edit,state", [
    (lambda snap: snap["vlan_cutover"][0].update(wave="Pilot, Later, measured"), UV),
    (lambda snap: snap["move_groups"].reverse(), UV),
    (lambda snap: [group.pop("group") for group in snap["move_groups"]], NC),
    (lambda snap: snap["move_groups"][0].pop("group"), UV),
    (lambda snap: snap["move_groups"][1].update(group="Later, measured"), UV),
    (lambda snap: snap["move_groups"][0]["switches"].append("edgeA"), UV),
    (lambda snap: snap["move_groups"][0].update(group=""), UV),
    (lambda snap: snap.update(move_groups=None), NC),
])
def test_stored_vlan_wave_cannot_bypass_label_membership_and_owner_order(edit, state):
    snap, _interfaces = _vlan_snapshot()
    assert _vlan_wave(snap)["state"] == PUB
    edit(snap)
    fact = _vlan_wave(snap)
    assert fact["state"] == state
    assert fact["value"] is None


def test_unmatched_hosts_are_omitted_and_a_blank_wave_is_not_collected():
    groups = [{"group": "Unrelated", "switches": ["elsewhere"]}]
    snap, _interfaces = _vlan_snapshot(groups)
    assert snap["vlan_cutover"][0]["wave"] == ""
    fact = _vlan_wave(snap)
    assert fact["state"] == NC
    assert fact["value"] is None


@pytest.mark.parametrize("edit", [
    lambda snap: snap.update(interfaces=[]),
    lambda snap: snap["interfaces"].update(edgeA=[]),
    lambda snap: snap["interfaces"]["edgeA"].update({"Gi1/0/1": []}),
    lambda snap: snap["interfaces"]["edgeA"]["Gi1/0/1"].update(vlan=10),
    lambda snap: snap["interfaces"]["edgeA"]["Gi1/0/1"].update(switchport_mode=True),
    lambda snap: snap.update(stp_roots=[]),
    lambda snap: snap["stp_roots"].update({"stp-only": []}),
    lambda snap: snap["stp_roots"]["stp-only"].update({"30": None}),
    lambda snap: snap["stp_roots"]["stp-only"]["30"].update(is_mst="false"),
])
def test_malformed_captured_vlan_universe_withholds_the_retained_wave(edit):
    snap, _interfaces = _vlan_snapshot()
    edit(snap)
    fact = _vlan_wave(snap)
    assert fact["state"] == UV
    assert fact["value"] is None


@pytest.mark.parametrize("section", ["interfaces", "stp_roots"])
def test_failed_empty_raw_vlan_inputs_are_unavailable_before_label_admission(section):
    snap, _interfaces = _vlan_snapshot()
    assert _vlan_wave(snap)["state"] == PUB
    snap[section] = {}
    # Raw capture/STP maps have no direct _run_phase label. The documented unclassified
    # failure boundary marks their empty fallback unavailable without inventing attribution.
    snap["assessment_integrity"] = {"failed_phases": ["Unclassified capture failure"]}
    assert ssot.abstention_reason(snap, section) == AU
    for other in ("vlan_cutover", "move_groups", "wave_sequencing", "interfaces", "stp_roots"):
        if other != section:
            assert ssot.abstention_reason(snap, other) != AU
    fact = _vlan_wave(snap)
    assert fact["state"] == AU
    assert fact["value"] is None


def _session_row(host):
    """A stored punch-list row that cites the device's sealed SSH session row, as the engine's ssh-legacy-transport
    fold writes it (analyze.compute_migration_punchlist): session-evidenced, needing no running-config."""
    return {"severity": "Medium", "devices": [host],
            "evidence_refs": [{"kind": "analysis_row", "host": host, "ref": "/ssh_sessions/rows/0",
                               "role": "derived_from", "cite": f"{host} SSH session record row"}]}


def test_w59_a_withheld_device_rollup_names_its_session_evidenced_findings():
    """W59 PR-1 review (P2-b). Catches: a running-config or collection gap hiding the findings that rest on the
    device's sealed SSH session record (a device refused at collection keeps no config). The counts stay withheld --
    configuration-derived rows may be missing -- while the reason states the floor and each such row is witnessed,
    on the configless path and on the blind (roster-forced) path alike."""
    snap = _snapshot(_stored_rows() + [_session_row("edgeA")])
    snap["software_risk"]["per_device"][0]["config_assessable"] = False
    for fact in _assert_held(snap, "edgeA", NC).values():
        assert "rest on its sealed SSH session record" in fact["reason"] and "worst Medium" in fact["reason"]
        assert {"pointer": "/punchlist/5", "role": "witness"} in fact["refs"]
    ghost = _snapshot(_stored_rows() + [_session_row("ghost")])
    ghost["collection_completeness"]["devices"] = [
        {"host": "ghost", "status": "not collected", "missing": ["interface status"], "data_quality": 0},
    ]
    ghost["collection_completeness"]["summary"]["inventory"] += 1
    for fact in _assert_held(ghost, "ghost", NC).values():
        assert "rest on its sealed SSH session record" in fact["reason"]
        assert {"pointer": "/punchlist/5", "role": "witness"} in fact["refs"]
    # non-vacuity: without a session-evidenced row the withheld reason claims no floor
    plain = _snapshot(_stored_rows())
    plain["software_risk"]["per_device"][0]["config_assessable"] = False
    assert all("SSH session record" not in fact["reason"] for fact in _assert_held(plain, "edgeA", NC).values())
