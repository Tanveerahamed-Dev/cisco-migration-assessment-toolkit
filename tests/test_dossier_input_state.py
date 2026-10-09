"""G49: dossier conclusions require collection records, including sparse parser receipts."""
import copy
import ast
import inspect
import json
from pathlib import Path

import pytest

from cisco_toolkit import analyze as A, build, cmdio, ssot


CONFIG_AXES = ("Security posture", "Config hygiene", "Golden drift", "QoS posture")
PLAIN_CONFIG = "\n".join([
    "hostname acc", "version 17.12", "service timestamps debug datetime msec",
    "service timestamps log datetime msec", "no ip http server", "no ip http secure-server",
    "ip ssh version 2", "no service pad", "service password-encryption", "logging buffered 8192",
    "interface GigabitEthernet1/0/1", " switchport mode access", " switchport access vlan 10",
    " spanning-tree portfast", "end", "",
])


def axes(**kwargs):
    kwargs.setdefault("health_scores", [{"switch": "h", "band": "Excellent", "score": 95}])
    return {e["axis"]: e for e in A.compute_device_dossiers(**kwargs)["per_device"][0]["exposures"]}


def producer_config_inputs(tmp_path, *, host="acc", parser_error=False, monkeypatch=None):
    folder = tmp_path / host
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "show_running-config.txt"
    path.write_text(PLAIN_CONFIG, encoding="utf-8")
    c2f = {"show running-config": str(path)}
    cmdio.reset_parse_ledger()
    security = {host: build.build_security(c2f)}
    if parser_error:
        def parse_config_hygiene(_text):
            raise RuntimeError("parser failure (test)")
        monkeypatch.setattr(build, "parse_config_hygiene", parse_config_hygiene)
    hygiene = build.build_config_hygiene(c2f)
    assert hygiene == {}
    return {
        "health_scores": [{"switch": host, "band": "Excellent", "score": 95}],
        "security": security, "config_hygiene": {},
        "software_risk": A.compute_software_risk({host: PLAIN_CONFIG}),
        "golden_drift": A.compute_golden_drift({host: PLAIN_CONFIG}),
        "qos_audit": A.compute_qos_audit({host: PLAIN_CONFIG}),
        "parse_yield": cmdio.parse_yield_report(),
    }


def test_config_hygiene_screened_empty_requires_successful_parse_receipt(tmp_path):
    inputs = producer_config_inputs(tmp_path)
    result = axes(**inputs)
    assert result["Config hygiene"]["state"] == "ok"
    assert result["Config hygiene"]["input_state"] == "collected_but_empty"
    assert "no captured" not in result["Config hygiene"]["label"]
    assert not any(result[a]["input_state"] == "not_collected" for a in CONFIG_AXES)
    inputs["parse_yield"] = None
    assert axes(**inputs)["Config hygiene"]["input_state"] == "analysis_unavailable"


def test_config_hygiene_parser_error_is_analysis_unavailable(tmp_path, monkeypatch):
    inputs = producer_config_inputs(tmp_path, parser_error=True, monkeypatch=monkeypatch)
    assert inputs["parse_yield"]["receipts"][0]["errors"] == 1
    assert axes(**inputs)["Config hygiene"]["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("field,value", [("zero_yield", True), ("zero_yield", "1"),
                                         ("zero_yield", -1), ("errors", False),
                                         ("errors", "0"), ("errors", -1), ("calls", 0)])
def test_malformed_parse_receipt_never_authorizes_clean(tmp_path, field, value):
    inputs = producer_config_inputs(tmp_path)
    receipt = next(r for r in inputs["parse_yield"]["receipts"] if r["parser"] == "parse_config_hygiene")
    receipt[field] = value
    assert axes(**inputs)["Config hygiene"]["input_state"] == "analysis_unavailable"


def test_conflicting_duplicate_receipts_never_authorize_clean(tmp_path):
    inputs = producer_config_inputs(tmp_path)
    receipt = next(r for r in inputs["parse_yield"]["receipts"] if r["parser"] == "parse_config_hygiene")
    inputs["parse_yield"]["receipts"].append({**receipt, "zero_yield": 0, "errors": 1})
    assert axes(**inputs)["Config hygiene"]["input_state"] == "analysis_unavailable"


def test_canonical_false_capture_dominates_inconsistent_rows():
    result = axes(software_risk={"per_device": [{"host": "h", "config_assessable": False,
                                                "sw_version": "17.12", "train_band": "Current-era"}]},
                  qos_audit={"per_device": [{"host": "h", "assessable": True}]},
                  security={"h": {"findings": [{"status": "fail", "severity": "high"}]}},
                  config_hygiene={"h": {"undefined": ["ACL1"]}},
                  golden_drift={"per_device": [{"host": "h", "n_missing": 10}],
                                "summary": {"n_baseline": 10}})
    for axis in CONFIG_AXES:
        assert result[axis]["state"] == "na"
        assert result[axis]["input_state"] == "not_collected"
        assert "no captured running-config" in result[axis]["label"]


@pytest.mark.parametrize("record", [{}, {"config_assessable": "False"}, {"config_assessable": 1}])
def test_unknown_capture_record_does_not_turn_missing_axis_into_not_collected(record):
    result = axes(software_risk={"per_device": [{"host": "h", **record}]})
    assert all(result[a]["input_state"] == "analysis_unavailable" for a in CONFIG_AXES)


@pytest.mark.parametrize("axis,kwargs", [
    ("Control plane", {"platform_health": A.compute_platform_health({"h": {
        "cpu": {}, "memory": {}, "system": {"uptime": "1d"}}})}),
    ("Operational logs", {"syslog_intelligence": A.compute_syslog_intelligence({
        "h": "Syslog logging: enabled\nLog Buffer (8192 bytes):\n"})}),
    ("Security posture", {"security": {"h": {"findings": [], "summary": {"pass": 0, "fail": 0, "na": 3}}},
                           "software_risk": {"per_device": [{"host": "h", "config_assessable": True}]}}),
])
def test_captured_but_nothing_to_judge_is_not_clean(axis, kwargs):
    result = axes(**kwargs)[axis]
    assert result["state"] == "na"
    assert result["input_state"] == "collected_but_empty"


def test_unknown_health_band_does_not_assert_health():
    result = axes(health_scores=[{"switch": "h", "band": "Great", "score": 95}])["Health"]
    assert result["state"] == "na"
    assert result["input_state"] == "analysis_unavailable"


def test_protocol_requires_valid_receipt_and_names_the_bounded_denominator(tmp_path):
    missing = A.compute_protocol_assessability(["h"], {"h": {}}, {"h": {}}, [])
    assert axes(protocol_assessability=missing)["Protocol"]["input_state"] == "not_collected"
    assert axes(protocol_assessability=missing)["Protocol"]["state"] == "na"
    assert axes()["Protocol"]["input_state"] == "analysis_unavailable"
    path = tmp_path / "stp.txt"
    path.write_text("VLAN0010\nRoot ID priority 32778\n", encoding="utf-8")
    health = [{"switch": "h", "protocol": "STP", "severity": "Info"}]
    partial = A.compute_protocol_assessability(["h"], {"h": {}}, {
        "h": {"show spanning-tree": str(path)}}, health)
    result = axes(protocol_assessability=partial, protocol_health=health)["Protocol"]
    assert result["state"] == "ok"
    assert "1 of 7 families" in result["label"] and "STP" in result["label"]
    partial["rows"].append(copy.deepcopy(partial["rows"][0]))
    result = axes(protocol_assessability=partial, protocol_health=health)["Protocol"]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("capture,state,input_state", [
    ("", "captured_empty", "collected_but_empty"),
    ("BGP router identifier 192.0.2.1, local AS number 65000\n",
     "captured_no_record", "collected_but_empty"),
    ("% BGP not active\n", "not_running", "collected_but_empty"),
    ("% Invalid input detected at '^' marker.\n", "capture_error", "not_collected"),
])
def test_protocol_capture_without_health_records_stays_unassessed(tmp_path, capture, state, input_state):
    path = tmp_path / "bgp.txt"
    path.write_text(capture, encoding="utf-8")
    receipt = A.compute_protocol_assessability(
        ["h"], {"h": {}}, {"h": {"show ip bgp summary": str(path)}}, [])
    assert next(r for r in receipt["rows"] if r["protocol"] == "BGP")["state"] == state
    assert A._validate_protocol_assessability_receipt(receipt)["valid"] is True
    result = axes(protocol_assessability=receipt)["Protocol"]
    assert result["state"] == "na"
    assert result["input_state"] == input_state


@pytest.mark.parametrize("conclusion,input_state", [
    ("abstained", "collected_but_empty"),
    ("not_running", "collected_but_empty"),
    ("blind", "not_collected"),
])
def test_protocol_future_state_uses_owner_conclusion(monkeypatch, conclusion, input_state):
    receipt = A.compute_protocol_assessability(["h"], {"h": {}}, {"h": {}}, [])
    view = A._validate_protocol_assessability_receipt(receipt)
    assert view["valid"] is True
    # Model a future producer/validator delivering a new state at the validated boundary.
    # The dossier must project its owner traits without adding another local state list.
    future_state = "future_no_health_record"
    view["index"][("h", "BGP")]["state"] = future_state
    monkeypatch.setitem(A._PROTOCOL_ASSESSABILITY_STATE_TRAITS, future_state,
                        {"health_row": "none", "conclusion": conclusion})
    monkeypatch.setattr(A, "_validate_protocol_assessability_receipt", lambda value: view)
    result = axes(protocol_assessability=receipt)["Protocol"]
    assert result["state"] == "na"
    assert result["input_state"] == input_state


def test_golden_drift_names_baseline_and_missing_capture():
    configs = {h: "service timestamps log datetime msec\nno ip http server\n" for h in ("h", "b", "c")}
    inputs = {"software_risk": A.compute_software_risk(configs, all_hosts=["h", "b", "c", "d"]),
              "golden_drift": A.compute_golden_drift(configs),
              "health_scores": [{"switch": h, "band": "Good"} for h in ("h", "b", "c", "d")]}
    rows = {r["host"]: {e["axis"]: e for e in r["exposures"]}
            for r in A.compute_device_dossiers(**inputs)["per_device"]}
    assert "2-directive majority baseline" in rows["h"]["Golden drift"]["label"]
    assert rows["d"]["Golden drift"]["input_state"] == "not_collected"


def test_registry_and_failed_phase_ratchet(tmp_path):
    registry = A.DOSSIER_AXIS_INPUTS
    inputs = producer_config_inputs(tmp_path, host="h")
    for label, sections in ssot.PHASE_SECTIONS.items():
        for axis, dependencies in registry.items():
            if not set(sections) & set(dependencies):
                continue
            result = axes(**inputs, input_failures=ssot.failed_sections({
                "assessment_integrity": {"failed_phases": [label]}}))[axis]
            assert result["state"] == "na", (label, axis)
            assert result["input_state"] == "analysis_unavailable", (label, axis)
            assert "not captured" not in result["label"], (label, axis)
    for name in ("tests/golden/snapshot.json", "webapp/sample_data/sample_fleet.snapshot.json"):
        snap = json.loads(Path(name).read_text(encoding="utf-8"))
        kwargs = {key: snap.get(key) for deps in registry.values() for key in deps}
        rows = A.compute_device_dossiers(**kwargs)["per_device"]
        assert rows
        for row in rows:
            assert tuple(e["axis"] for e in row["exposures"]) == tuple(registry)
            for e in row["exposures"]:
                assert e["input_state"] in ssot.ABSTENTION_STATES
                if e["state"] != "na":
                    assert e["input_state"] in ("published", "collected_but_empty")
                if e["state"] == "ok" and e["input_state"] == "collected_but_empty":
                    assert e["axis"] in A.DOSSIER_EMPTY_IS_CLEAN
            config_not_collected = {e["axis"] for e in row["exposures"]
                                    if e["axis"] in CONFIG_AXES and e["input_state"] == "not_collected"}
            assert config_not_collected in (set(), set(CONFIG_AXES))
        if "sample_fleet" in name:
            access13 = next(r for r in rows if r["host"] == "access13")
            assert next(e for e in access13["exposures"] if e["axis"] == "Config hygiene")["state"] == "ok"


def test_new_inputs_are_keyword_only():
    signature = inspect.signature(A.compute_device_dossiers)
    for name in ("protocol_assessability", "parse_yield", "input_failures"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_unscheduled_device_has_the_owned_wave_sentinel():
    row = A.compute_device_dossiers(health_scores=[{"switch": "h", "band": "Good"}])["per_device"][0]
    assert row["wave"] == A.MOVE_GROUP_UNSCHEDULED


def test_unknown_health_band_cannot_authorize_physical_by_silence():
    result = axes(health_scores=[{"switch": "h", "band": "Great"}])["Physical"]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("band", [[], {}, ["Good"], {"band": "Good"}])
def test_unhashable_health_band_cannot_authorize_physical_or_raise(band):
    result = axes(health_scores=[{"switch": "h", "band": band, "score": 75}])
    for name in ("Health", "Physical"):
        assert result[name]["state"] == "na"
        assert result[name]["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("band", ["Excellent", "Good", "Fair", "Poor", "Critical"])
def test_recognized_health_band_still_proves_physical_scan(band):
    physical = axes(health_scores=[{"switch": "h", "band": band, "score": 75}])["Physical"]
    assert physical["state"] == "ok"
    assert physical["input_state"] == "collected_but_empty"


def test_sanitized_parse_receipt_has_exact_custody_and_rejects_collisions(tmp_path):
    inputs = producer_config_inputs(tmp_path, host="h_1")
    for section in ("software_risk", "golden_drift", "qos_audit"):
        inputs[section]["per_device"][0]["host"] = "h/1"
    inputs["security"]["h/1"] = inputs["security"].pop("h_1")
    inputs["health_scores"][0]["switch"] = "h/1"
    assert axes(**inputs)["Config hygiene"]["state"] == "ok"
    inputs["health_scores"].append({"switch": "h:1", "band": "Good"})
    row = next(r for r in A.compute_device_dossiers(**inputs)["per_device"] if r["host"] == "h/1")
    assert next(e for e in row["exposures"] if e["axis"] == "Config hygiene")["input_state"] == "analysis_unavailable"


def test_malformed_unhashable_protocol_receipt_fails_closed():
    receipt = A.compute_protocol_assessability(["h"], {"h": {}}, {"h": {}}, [])
    states = receipt["rows"][0]["input_states"]
    states[next(iter(states))] = {}
    result = axes(protocol_assessability=receipt)["Protocol"]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"


def test_failed_protocol_receipt_without_external_failures_remains_unavailable():
    receipt = A.compute_protocol_assessability(["h"], {"h": {}}, {"h": {}}, [], analysis_available=False)
    assert axes(protocol_assessability=receipt)["Protocol"]["input_state"] == "analysis_unavailable"


def test_unattributed_failure_only_invalidates_deep_empty_inputs():
    kwargs = {"input_failures": (frozenset(), True), "platform_health": {"per_device": [], "findings": []}}
    assert axes(**kwargs)["Control plane"]["input_state"] == "analysis_unavailable"
    assert axes(**kwargs)["Health"]["state"] == "ok"


def test_call_sites_pass_every_new_argument():
    import COLLECT_PARSE_V3_23_0 as cp
    import test_pipeline_golden as golden

    signature = inspect.signature(A.compute_device_dossiers)
    # W33's ratchet closed by W48: the AssessHub section recompute (webapp/backend/app.py) now passes the engine
    # owner's failure-impact verdicts too, so every call site passes every argument. Keep this empty: a call site
    # that drops an argument is a regression, not a new pending entry.
    pending: dict = {}
    for filename in ("COLLECT_PARSE_V3_23_0.py", "webapp/backend/app.py"):
        tree = ast.parse(Path(filename).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "compute_device_dossiers"]
        assert len(calls) == 1
        assert ({keyword.arg for keyword in calls[0].keywords}
                == set(signature.parameters) - pending.get(filename, set())), filename
    assert set(golden._DOSSIER_SECTIONS) | {"lifecycle_risk", "input_failures",
                                            "failure_impact_assessability"} == set(signature.parameters)
    # Forwarding a default context still closes the keyword-only receipt/failure inputs.
    tree = ast.parse(inspect.getsource(cp._device_dossiers))
    assert {k.arg for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "compute_device_dossiers"
            for k in n.keywords} == set(signature.parameters)


def test_sanitized_collision_also_withholds_an_exact_spelling(tmp_path):
    inputs = producer_config_inputs(tmp_path, host="a_b")
    inputs["health_scores"].append({"switch": "a/b", "band": "Good"})
    row = next(r for r in A.compute_device_dossiers(**inputs)["per_device"] if r["host"] == "a_b")
    assert next(e for e in row["exposures"] if e["axis"] == "Config hygiene")["input_state"] == "analysis_unavailable"


def test_malformed_canonical_capture_cannot_be_replaced_with_a_positive_fallback():
    result = axes(software_risk={"per_device": [{"host": "h", "config_assessable": "False"}]},
                  qos_audit={"per_device": [{"host": "h", "assessable": True}]})
    assert all(result[a]["input_state"] == "analysis_unavailable" for a in CONFIG_AXES)


def test_unknown_capture_withholds_success_looking_axis_records():
    result = axes(security={"h": {"findings": [{"status": "pass"}]}},
                  config_hygiene={"h": {"undefined": []}},
                  golden_drift={"per_device": [{"host": "h", "n_missing": 0, "compliance_pct": 100}],
                                "summary": {"n_baseline": 2}, "mode": "majority"})
    assert all(result[a]["input_state"] == "analysis_unavailable" for a in CONFIG_AXES)


@pytest.mark.parametrize("row", [{"n_missing": None, "compliance_pct": {}},
                                 {"n_missing": "0", "compliance_pct": "100"},
                                 {"n_missing": False, "compliance_pct": True},
                                 {"n_missing": -1, "compliance_pct": 101}])
def test_malformed_golden_counts_cannot_assert_compliance(row):
    result = axes(software_risk={"per_device": [{"host": "h", "config_assessable": True}]},
                  golden_drift={"per_device": [{"host": "h", **row}],
                                "summary": {"n_baseline": 2}, "mode": "majority"})["Golden drift"]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("row", [{"cpu_5min": "many", "mem_free_pct": {}},
                                 {"cpu_5min": False, "mem_free_pct": None},
                                 {"cpu_5min": None, "mem_free_pct": None},
                                 {"cpu_5min": -1, "mem_free_pct": 110}])
def test_malformed_control_plane_figures_cannot_assert_capacity(row):
    result = axes(platform_health={"per_device": [{"host": "h", "collected": True, "band": "OK", **row}]})["Control plane"]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("kwargs,axis", [
    ({"software_risk": {"per_device": [{"host": "h", "config_assessable": True}],
                        "findings": [{"host": "h", "severity": {}}]}}, "Software risk"),
    ({"software_risk": {"per_device": [{"host": "h", "config_assessable": True}],
                        "findings": [{"host": {}, "severity": "High"}]}}, "Software risk"),
    ({"physical_health": [{"switch": "h", "severity": "High", "risk": 5}]}, "Physical"),
])
def test_malformed_sparse_findings_withhold_conclusions_without_raising(kwargs, axis):
    result = axes(**kwargs)[axis]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"


@pytest.mark.parametrize("kwargs,axis", [
    ({"platform_health": {"per_device": [{"host": "h", "collected": True, "band": "OK",
                                         "cpu_5min": 10**1000, "mem_free_pct": None}]}}, "Control plane"),
    ({"software_risk": {"per_device": [{"host": "h", "config_assessable": True}]},
      "golden_drift": {"per_device": [{"host": "h", "n_missing": 10**1000, "compliance_pct": 0}],
                       "summary": {"n_baseline": 10**1000}, "mode": "majority"}}, "Golden drift"),
])
def test_overflowing_numeric_values_fail_closed_without_raising(kwargs, axis):
    result = axes(**kwargs)[axis]
    assert result["state"] == "na" and result["input_state"] == "analysis_unavailable"
