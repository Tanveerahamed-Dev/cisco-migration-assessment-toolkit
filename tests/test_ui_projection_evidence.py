"""W2a evidence projection: producer parity and adversarial coverage honesty."""
from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.model import InterfaceData

ROOT = Path(__file__).resolve().parent.parent
PUB, NC, CBE, UV, AU = "published", "not_collected", "collected_but_empty", "unverified", "analysis_unavailable"


def _ref(pointer="/interfaces/sw.lab/Gi1~10~01", **kwargs):
    return {"kind": "interface", "host": "sw.lab", "ref": pointer, "role": "subject",
            "cite": "sw.lab Gi1/0~1", **kwargs}


def _snap():
    return {"devices": {"sw.lab": {}}, "interfaces": {"sw.lab": {"Gi1/0~1": {"port": "Gi1/0~1"}}},
            "health_scores": [{"switch": "sw.lab", "band": "Good", "score": 85, "deductions": ["first", "second"],
                               "deduction_refs": [_ref()]}],
            "punchlist": [{"devices": ["sw.lab"], "evidence_basis": "record", "evidence_refs": [_ref()]}]}


def _finding(snap):
    return uip.project_findings(snap)["rows"]["items"][0]


def _health(snap):
    return uip.project_device(snap, "sw.lab")["device"]["health"]


def _values(listing):
    return [item["fact"]["value"] for item in listing["items"]]


def _validate(snap):
    for document in (uip.project(snap), uip.project_device(snap, "sw.lab")):
        schema = uip.ui_projection_schema()
        if "device" in document:
            schema = {"$ref": "#/$defs/DeviceDocument", "$defs": schema["$defs"]}
        errors = list(Draft202012Validator(schema).iter_errors(document))
        assert not errors, [(list(error.path), error.message) for error in errors]
        json.dumps(document, allow_nan=False).encode("utf-8")


def test_current_sample_evidence_is_projected_verbatim_and_schema_closed():
    snap = json.loads((ROOT / "webapp/sample_data/sample_fleet.snapshot.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(snap)
    findings = uip.project_findings(snap)
    assert findings["rows"]["items"]
    assert "punch_rows_carry_no_evidence_pointers" not in findings["rows"].get("caveats", [])
    for raw, row in zip(snap["punchlist"], findings["rows"]["items"]):
        assert row["evidence_basis"]["state"] == PUB
        assert row["evidence_basis"]["value"] == raw["evidence_basis"]
        assert _values(row["evidence_refs"]) == raw["evidence_refs"]
        for i, item in enumerate(row["evidence_refs"]["items"]):
            assert item["index"] == i
            assert item["pointer"] == f"{row['pointer']}/evidence_refs/{i}"
        total = row["evidence_refs_total"]
        assert total["state"] == (PUB if "evidence_refs_total" in raw else NC)
        assert total["value"] == raw.get("evidence_refs_total")
    for raw in snap["health_scores"]:
        projected = uip.project_device(snap, raw["switch"])["device"]["health"]
        assert _values(projected["deduction_refs"]) == raw["deduction_refs"]
    _validate(snap)
    assert snap == before


def test_evidence_vocabularies_are_the_engine_owners():
    for name in ("PUNCH_EVIDENCE_BASES", "PUNCH_EVIDENCE_REF_KINDS", "PUNCH_EVIDENCE_RECORD_KINDS",
                 "PUNCH_EVIDENCE_ROLES", "PUNCH_EVIDENCE_REFS_CAP", "PUNCH_EVIDENCE_RULES"):
        assert getattr(uip, name) == getattr(analyze, name), name
    defs = uip.ui_projection_schema()["$defs"]
    value = defs["EvidenceRefValue"]["properties"]
    assert value["kind"]["enum"] == list(analyze.PUNCH_EVIDENCE_REF_KINDS)
    assert value["role"]["enum"] == list(analyze.PUNCH_EVIDENCE_ROLES)
    fact = defs["EvidenceBasisFact"]["oneOf"][0]
    assert fact["properties"]["value"]["enum"] == list(analyze.PUNCH_EVIDENCE_BASES)
    assert set(analyze.PUNCH_EVIDENCE_RULES) == {"total_only_when_capped", "absence_forbids_record_kinds",
                                               "record_requires_record_kind", "row_requires_ref",
                                               "host_must_be_row_device_or_null"}


@pytest.mark.parametrize("field", ["evidence_refs", "evidence_basis"])
def test_partial_evidence_pair_is_not_a_legacy_row(field):
    snap = _snap()
    del snap["punchlist"][0][field]
    assert _finding(snap)[field]["state"] == NC
    assert "punch_rows_carry_no_evidence_pointers" not in uip.project_findings(snap)["rows"].get("caveats", [])
    snap["punchlist"][0][field] = None
    assert _finding(snap)[field]["state"] == UV
    assert "punch_rows_carry_no_evidence_pointers" not in uip.project_findings(snap)["rows"].get("caveats", [])


def test_present_empty_absence_and_legacy_health_are_distinct():
    snap = _snap()
    snap["punchlist"][0].update(evidence_basis="absence", evidence_refs=[])
    assert _finding(snap)["evidence_basis"]["value"] == "absence"
    assert _finding(snap)["evidence_refs"]["state"] == CBE
    snap["health_scores"][0]["deduction_refs"] = []
    assert _health(snap)["deduction_refs"]["state"] == CBE
    del snap["health_scores"][0]["deduction_refs"]
    assert _health(snap)["deduction_refs"]["state"] == NC
    del snap["punchlist"][0]["evidence_basis"]
    del snap["punchlist"][0]["evidence_refs"]
    assert "punch_rows_carry_no_evidence_pointers" in uip.project_findings(snap)["rows"]["caveats"]


@pytest.mark.parametrize("bad", [None, 5, {}, "refs", [None], [5], [_ref(kind="future")],
                                  [_ref(role="basis")], [_ref(host=[])], [_ref(host=" ")],
                                  [_ref(host="other")], [_ref(cite=float("nan"))],
                                  [_ref(cite="bad\ud800")], [_ref(extra="not allowed")],
                                  [{k: v for k, v in _ref().items() if k != "host"}]])
def test_malformed_ref_never_publishes_or_leaks(bad):
    snap = _snap()
    snap["punchlist"][0]["evidence_refs"] = bad
    snap["health_scores"][0]["deduction_refs"] = bad
    for listing in (_finding(snap)["evidence_refs"], _health(snap)["deduction_refs"]):
        assert listing["state"] == UV
        assert all(item["fact"]["state"] != PUB for item in listing["items"])
    assert _finding(snap)["evidence_basis"]["state"] == UV
    _validate(snap)


@pytest.mark.parametrize("pointer", ["interfaces.sw.lab", "/missing", "/interfaces/sw.lab/Gi1~20~01",
                                      "/interfaces/sw.lab/Gi1~", "/array/00", "/array/-", "/array/-1",
                                      "/array/١", pytest.param("/array/" + "9" * 5000, id="huge-index"),
                                      "/null"])
def test_bad_pointer_is_withheld(pointer):
    snap = _snap()
    snap["array"] = [1]
    snap["null"] = None
    snap["punchlist"][0]["evidence_refs"] = [_ref(pointer)]
    assert _finding(snap)["evidence_refs"]["state"] == UV
    assert _values(_finding(snap)["evidence_refs"]) == [None]
    _validate(snap)


@pytest.mark.parametrize("pointer,target", [("/numeric/00", {"00": 1}), ("/numeric/1", {1: "numeric key"}),
                                            ("/numeric/~01", {"~1": "decode once"}), ("/numeric/0", [1])])
def test_resolved_pointer_preserves_original_bytes(pointer, target):
    snap = _snap()
    snap["numeric"] = target
    snap["punchlist"][0]["evidence_refs"] = [_ref(pointer)]
    assert _values(_finding(snap)["evidence_refs"])[0]["ref"] == pointer


@pytest.mark.parametrize("basis,refs", [("record", []), ("row", []), ("row", [_ref()]),
                                       ("absence", [_ref()]), ("record", [_ref(kind="analysis_row")]),
                                       ("future", [_ref()])])
def test_inconsistent_basis_withholds_claim_and_refs(basis, refs):
    snap = _snap()
    snap["punchlist"][0].update(evidence_basis=basis, evidence_refs=refs)
    row = _finding(snap)
    assert row["evidence_basis"]["state"] == row["evidence_refs"]["state"] == UV


@pytest.mark.parametrize("total", [True, -1, 64, 1.0, 65.0, None, "65", 2 ** 53])
def test_invalid_capped_total_is_withheld(total):
    snap = _snap()
    snap["punchlist"][0].update(evidence_refs=[_ref()] * 64, evidence_refs_total=total)
    row = _finding(snap)
    assert row["evidence_refs_total"]["state"] == UV
    assert row["evidence_refs_cap"]["reached"] is None
    _validate(snap)


def test_capped_total_is_preserved_never_recounted_or_invented():
    snap = _snap()
    snap["punchlist"][0].update(evidence_refs=[_ref()] * 64, evidence_refs_total=1007)
    row = _finding(snap)
    assert row["evidence_refs_total"]["value"] == 1007
    assert row["evidence_refs_cap"]["total"] == row["evidence_refs_total"]
    assert row["evidence_refs_cap"]["reached"] is True
    assert "engine_list_capped" in row["evidence_refs"]["caveats"]
    del snap["punchlist"][0]["evidence_refs_total"]
    row = _finding(snap)
    assert row["evidence_refs_total"]["state"] == NC
    assert row["evidence_refs_total"]["value"] is None
    snap["punchlist"][0]["evidence_refs_total"] = 1007
    snap["punchlist"][0]["evidence_refs"].pop()
    assert _finding(snap)["evidence_refs_total"]["state"] == UV


@pytest.mark.parametrize("phase", ["Health Scores", "Migration Punch-List"])
def test_failed_phase_withholds_stale_evidence(phase):
    snap = _snap()
    snap["assessment_integrity"] = {"failed_phases": [phase]}
    listing = (_health(snap)["deduction_refs"] if phase == "Health Scores"
               else _finding(snap)["evidence_refs"])
    assert listing["state"] == AU
    assert all(item["fact"]["state"] == AU for item in listing["items"])
    assert {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"} in listing["refs"]


def test_real_health_producer_refs_are_subsequence_not_deduction_positions():
    interfaces = {"sw.lab": {"Gi1/0~1": InterfaceData(port="Gi1/0~1", status="connected")}}
    physical = [{"switch": "sw.lab", "port": None, "risk": "err-disabled"},
                {"switch": "sw.lab", "port": "Gi1/0~1", "risk": "err-disabled"}]
    health = analyze.compute_health_scores(interfaces, physical, [], [], [])
    # Exercise the producer's missing-ref case without ever assigning the sole ref to deductions[0].
    assert len(health[0]["deductions"]) == 2
    assert len(health[0]["deduction_refs"]) == 1
    snap = _snap()
    snap["health_scores"] = health
    projected = _health(snap)
    assert _values(projected["deduction_refs"]) == health[0]["deduction_refs"]
    assert set(projected["deduction_refs"]["items"][0]) == {"index", "pointer", "fact"}
    assert projected["deduction_refs"]["items"][0]["pointer"] == "/health_scores/0/deduction_refs/0"
    assert "deduction_refs_are_subsequence" in projected["deduction_refs"]["caveats"]


def test_evidence_ref_schema_rejects_unknown_or_missing_fields():
    snap = _snap()
    doc = uip.project(snap)
    ref = doc["findings"]["rows"]["items"][0]["evidence_refs"]["items"][0]["fact"]["value"]
    validator = Draft202012Validator(uip.ui_projection_schema())
    validator.validate(doc)
    ref["unexpected"] = True
    assert list(validator.iter_errors(doc))
    del ref["unexpected"]
    del ref["host"]
    assert list(validator.iter_errors(doc))


def test_real_capped_upstream_total_and_health_prefix_are_preserved():
    interfaces = {"sw.lab": {f"Gi1/0/{i}": InterfaceData(trunk_status="trunking", trunk_native_vlan="1")
                              for i in range(1, 81)}}
    drift = [row for row in analyze.compute_operational_drift(interfaces, [], []) if "Native VLAN 1" in row["title"]]
    punch = analyze.compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], drift=drift)
    snap = _snap()
    snap.update(interfaces={h: {p: dataclasses.asdict(v) for p, v in ports.items()} for h, ports in interfaces.items()},
                operational_drift=drift, punchlist=punch)
    row = _finding(snap)
    assert drift[0]["evidence_refs_total"] == 80
    assert punch[0]["evidence_refs_total"] == row["evidence_refs_total"]["value"] == 81
    assert _values(row["evidence_refs"]) == punch[0]["evidence_refs"]

    physical = [{"switch": "sw.lab", "port": port, "risk": "err-disabled"}
                for port in [None] + list(interfaces["sw.lab"])[:10]]
    snap["health_scores"] = analyze.compute_health_scores(interfaces, physical, [], [], [])
    health = _health(snap)
    assert len(snap["health_scores"][0]["deductions"]) == 8
    assert len(health["deduction_refs"]["items"]) == 7
    assert health["deduction_refs_cap"]["reached"] is True
    assert health["deduction_refs_cap"]["total"]["state"] == NC
    assert "engine_list_capped" in health["deduction_refs"]["caveats"]
    assert _values(health["deduction_refs"]) == snap["health_scores"][0]["deduction_refs"]
    _validate(snap)


@pytest.mark.parametrize("fallback", ["retained", "missing", [], None])
def test_failed_referenced_source_withholds_basis_refs_and_total(fallback):
    snap = _snap()
    snap["punchlist"][0].update(evidence_basis="row", evidence_refs=[_ref("/health_scores/0", kind="analysis_row")])
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    if fallback == "missing":
        del snap["health_scores"]
    elif fallback != "retained":
        snap["health_scores"] = fallback
    row = _finding(snap)
    for field in ("evidence_basis", "evidence_refs", "evidence_refs_total"):
        assert row[field]["state"] == AU
        assert {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"} in row[field]["refs"]
    assert _values(row["evidence_refs"]) == [None]


@pytest.mark.parametrize("target,pointer", [({10 ** 5000: 1}, "/numeric/absent"),
                                            ({"1": "string", 1: "integer"}, "/numeric/1")],
                         ids=["huge-integer-key", "serialized-key-collision"])
def test_poisoned_numeric_map_cannot_crash_or_ambiguously_resolve(target, pointer):
    snap = _snap()
    snap["numeric"] = target
    snap["punchlist"][0]["evidence_refs"] = [_ref(pointer)]
    assert _finding(snap)["evidence_refs"]["state"] == UV


def test_orphan_total_is_malformed_not_legacy():
    snap = _snap()
    snap["punchlist"] = [{"devices": ["sw.lab"], "evidence_refs_total": 99}]
    row = _finding(snap)
    assert row["evidence_refs"]["state"] == row["evidence_refs_total"]["state"] == UV
    assert "punch_rows_carry_no_evidence_pointers" not in uip.project_findings(snap)["rows"].get("caveats", [])
