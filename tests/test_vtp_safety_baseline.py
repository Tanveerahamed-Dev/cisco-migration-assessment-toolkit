"""Strict, source-bound VTP cutover-safety receipt counterexamples."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cisco_toolkit import vtp_safety as vtp
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.vtp_safety import (
    VTP_SAFETY_SCHEMA,
    compute_vtp_safety_baseline,
    compute_vtp_safety_subject_scope,
    embedded_vtp_safety_baseline,
    scope_vtp_safety_subjects,
    validate_vtp_safety_baseline,
)


def _status(
        mode: str = "Server", *, domain: str | None = "CAMPUS",
        revision: int | str | None = 100, version: str | None = "2",
        extra: str = "") -> str:
    lines = []
    if version is not None:
        lines.append(f"VTP version running             : {version}")
    if domain is not None:
        lines.append(f"VTP Domain Name                 : {domain}")
    lines.append(f"VTP Operating Mode              : {mode}")
    if revision is not None:
        lines.append(f"Configuration Revision          : {revision}")
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def _owner(
        tmp_path: Path, body: str, *, host: str = "edge1",
        devices: object | None = None) -> tuple[dict, dict, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{host}-show-vtp-status.txt"
    path.write_text(body, encoding="utf-8")
    paths = {host: {"show vtp status": str(path)}}
    integrity = compute_capture_integrity_from_paths(paths)
    baseline = compute_vtp_safety_baseline(
        paths, integrity,
        devices if devices is not None else {host: {"platform": "ios-xe"}},
    )
    return baseline, paths, integrity


def test_high_revision_server_is_review_never_degraded_or_accepted(tmp_path: Path):
    baseline, _paths, _integrity = _owner(tmp_path, _status(revision=100))

    assert baseline["schema"] == VTP_SAFETY_SCHEMA
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["assessed"] is False
    assert baseline["summary"]["n_high_revision_servers"] == 1
    assert baseline["summary"]["by_status"] == {
        "review": 1, "not_verified": 0, "assessed": 0,
    }
    row = baseline["rows"][0]
    assert row["mode"] == "server"
    assert row["revision"] == 100 and row["revision_present"] is True
    assert row["status"] == "review"
    assert row["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert "matching revision after cutover is NOT ACCEPTANCE" in row["acceptance"]
    assert "degraded" not in json.dumps(baseline).lower()
    assert validate_vtp_safety_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize(
    ("body", "expected_mode"),
    [
        (_status("Server", revision=99), "server"),
        (_status("Client", revision=4), "client"),
        (_status("Transparent", domain=None, revision=None), "transparent"),
        (_status("Off", domain=None, revision=None), "off"),
    ],
)
def test_low_and_nonactive_modes_are_bounded_assessed(
        tmp_path: Path, body: str, expected_mode: str):
    baseline, _paths, _integrity = _owner(tmp_path, body)

    assert baseline["verdict"] == "CLEAR"
    assert baseline["assessed"] is True
    assert baseline["rows"][0]["mode"] == expected_mode
    assert baseline["rows"][0]["status"] == "assessed"
    assert baseline["findings"] == []


@pytest.mark.parametrize(
    "body",
    [
        "VTP is disabled.\n",
        "VTP feature is not enabled\n",
        "VTP is not supported on this platform.\n",
        "VTP feature is not available\n",
    ],
)
def test_exact_disabled_or_unsupported_receipt_is_neutral_no_subject(
        tmp_path: Path, body: str):
    baseline, _paths, _integrity = _owner(tmp_path, body)

    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["assessed"] is False
    assert baseline["rows"] == []
    assert baseline["findings"] == []
    assert baseline["coverage"][0]["capture_status"] == "ok"
    assert baseline["coverage"][0]["subject"] is False
    assert baseline["coverage"][0]["status"] == "not_applicable"
    assert baseline["coverage"][0]["parser_status"] == "explicit_no_subject"
    assert baseline["coverage"][0]["explicit_no_subject"] is True
    assert validate_vtp_safety_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_nonexact_disabled_text_is_positive_subject_not_verified(tmp_path: Path):
    baseline, _paths, _integrity = _owner(
        tmp_path, "VTP is disabled on this device because of policy\n")

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["coverage"][0]["subject"] is True
    assert baseline["rows"][0]["status"] == "not_verified"
    assert baseline["rows"][0]["findings"][0]["code"] == "parser_not_verified"


def test_disabled_text_without_unique_integrity_receipt_is_not_neutral(tmp_path: Path):
    _baseline, paths, integrity = _owner(tmp_path, "VTP is disabled.\n")
    incomplete = copy.deepcopy(integrity)
    incomplete["inspections"][0]["status"] = "incomplete"

    withheld = compute_vtp_safety_baseline(paths, incomplete)

    assert withheld["verdict"] == "INDETERMINATE"
    assert withheld["coverage"][0]["subject"] is True
    assert withheld["coverage"][0]["explicit_no_subject"] is False
    assert withheld["rows"][0]["status"] == "not_verified"
    assert withheld["rows"][0]["findings"][0]["code"] == "capture_not_verified"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (_status("Server", revision=None), "not_verified", "active_mode_fields_not_verified"),
        (_status("Server", domain=None), "not_verified", "active_mode_fields_not_verified"),
        (_status("Server", domain=""), "review", "active_mode_domain_empty"),
        (_status("Server", revision="not-a-number"), "not_verified", "parser_not_verified"),
    ],
)
def test_active_mode_presence_and_parse_gaps_are_not_false_clear(
        tmp_path: Path, body: str, status: str, code: str):
    baseline, _paths, _integrity = _owner(tmp_path, body)

    row = baseline["rows"][0]
    assert row["status"] == status
    assert row["findings"][0]["code"] == code
    assert baseline["verdict"] == "INDETERMINATE"


def test_numeric_zero_revision_is_distinctly_present_and_assessed(tmp_path: Path):
    baseline, _paths, _integrity = _owner(tmp_path, _status(revision=0))

    row = baseline["rows"][0]
    assert row["revision"] == 0
    assert row["revision_present"] is True
    assert row["status"] == "assessed"


@pytest.mark.parametrize(
    "body",
    [
        _status("Primary Server", revision=99),
        _status("Server", revision="9" * 5_000),
    ],
)
def test_unrecognized_mode_and_oversized_revision_are_bounded_not_verified(
        tmp_path: Path, body: str):
    baseline, _paths, _integrity = _owner(tmp_path, body)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["rows"][0]["status"] == "not_verified"
    assert baseline["coverage"][0]["parser_status"] == "rejected"
    assert validate_vtp_safety_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_capture_integrity_missing_duplicate_and_incomplete_withhold_truth(tmp_path: Path):
    baseline, paths, integrity = _owner(tmp_path, _status(revision=99))
    assert baseline["verdict"] == "CLEAR"

    variants = [{"inspections": []}, copy.deepcopy(integrity)]
    variants[1]["inspections"].append(dict(variants[1]["inspections"][0]))
    for receipt, expected_capture in zip(
            variants, ("inspection_missing", "inspection_duplicate"), strict=True):
        withheld = compute_vtp_safety_baseline(paths, receipt)
        assert withheld["verdict"] == "INDETERMINATE"
        assert withheld["coverage"][0]["capture_status"] == expected_capture
        assert withheld["rows"][0]["status"] == "not_verified"
        assert withheld["rows"][0]["findings"][0]["code"] == "capture_not_verified"

    incomplete = copy.deepcopy(integrity)
    incomplete["inspections"][0]["status"] = "incomplete"
    withheld = compute_vtp_safety_baseline(paths, incomplete)
    assert withheld["coverage"][0]["capture_status"] == "incomplete"
    assert withheld["rows"][0]["status"] == "not_verified"


def test_json_deepcopy_and_embedded_projection_cannot_authorize_current_run(tmp_path: Path):
    baseline, _paths, _integrity = _owner(tmp_path, _status(revision=99))

    projections = {
        "json": json.loads(json.dumps(baseline)),
        "deepcopy": copy.deepcopy(baseline),
        "embedded": embedded_vtp_safety_baseline(baseline),
    }
    assert projections["json"]["projection_custody"] == "current_run_source_bound"
    for name in ("deepcopy", "embedded"):
        assert projections[name]["projection_custody"] == "embedded_unverified"
        assert projections[name]["rows"][0]["projection_custody"] == "embedded_unverified"
    for projection in projections.values():
        view = validate_vtp_safety_baseline(projection)
        assert view["valid"] is True
        assert view["source_bound"] is False
        rejected = validate_vtp_safety_baseline(
            projection, require_current_run=True)
        assert rejected == {
            "present": True, "valid": False,
            "reason": "baseline_not_current_run_source_bound",
            "source_bound": False, "rows": [], "index": {}, "baseline": {},
        }


def test_structural_tamper_and_coherent_marker_reseal_cannot_authorize(tmp_path: Path):
    high, _paths, _integrity = _owner(
        tmp_path / "high", _status(revision=100), host="high")
    forged = json.loads(json.dumps(high))
    forged["rows"][0]["status"] = "assessed"
    assert validate_vtp_safety_baseline(forged)["valid"] is False

    low, _paths, _integrity = _owner(
        tmp_path / "low", _status(revision=99), host="low")
    high.clear()
    high.update(dict(low))
    ordinary = validate_vtp_safety_baseline(high)
    assert ordinary["valid"] is True
    assert ordinary["source_bound"] is False
    assert validate_vtp_safety_baseline(
        high, require_current_run=True)["reason"] == "baseline_not_current_run_source_bound"


def test_receipt_is_path_free_raw_free_closed_and_reconciled(tmp_path: Path):
    secret = "DO-NOT-PUBLISH-RAW-VTP-PASSWORD"
    baseline, _paths, _integrity = _owner(
        tmp_path, _status(revision=100, extra=f"VTP Password: {secret}"))
    serialized = json.dumps(baseline)

    assert str(tmp_path) not in serialized
    assert secret not in serialized
    assert set(baseline) == {
        "schema", "scope", "verdict", "assessed", "projection_custody",
        "rows", "coverage", "findings", "summary", "limitations",
    }
    assert baseline["summary"]["n_hosts"] == len(baseline["coverage"])
    assert baseline["summary"]["n_subject_hosts"] == len(baseline["rows"])
    assert baseline["coverage"][0]["finding_codes"] == [
        finding["code"] for finding in baseline["rows"][0]["findings"]
    ]


def test_safe_subject_scoper_has_only_identity_platform_and_command(tmp_path: Path):
    _baseline, paths, _integrity = _owner(tmp_path, _status(revision=99))

    scoped = scope_vtp_safety_subjects(
        paths, {"edge1": {"platform": "ios-xe", "path": "must-not-leak"}})

    assert scoped == {
        "schema": "vtp_safety_subject_scope/1", "valid": True,
        "attempted": True, "reason": "ok", "rows": [{
            "switch": "edge1", "platform": "ios-xe", "command": "show vtp status",
        }],
    }
    assert str(tmp_path) not in json.dumps(scoped)

    neutral = compute_vtp_safety_subject_scope({"edge1": {"show version": "ignored"}})
    assert neutral == {
        "schema": "vtp_safety_subject_scope/1", "valid": True,
        "attempted": False, "reason": "ok", "rows": [],
    }


def test_subject_scope_receipt_distinguishes_rejected_attempts_from_no_subject():
    malformed = {"bad\nhost": {"show vtp status": "must-not-leak"}}
    rejected = compute_vtp_safety_subject_scope(malformed)
    assert rejected == {
        "schema": "vtp_safety_subject_scope/1", "valid": False,
        "attempted": True, "reason": "scope_identity_invalid", "rows": [],
    }
    over_cap = {
        f"edge{index}": {"show vtp status": "must-not-leak"}
        for index in range(4097)
    }
    rejected = compute_vtp_safety_subject_scope(over_cap)
    assert rejected["valid"] is False
    assert rejected["attempted"] is True
    assert rejected["reason"] == "scope_host_cap_exceeded"
    assert rejected["rows"] == []
    assert "must-not-leak" not in json.dumps(rejected)


def test_casefold_host_aliases_fail_closed_in_compute_scoper_and_validator(tmp_path: Path):
    path = tmp_path / "vtp.txt"
    path.write_text(_status(revision=99), encoding="utf-8")
    aliases = {
        "edge1": {"show vtp status": str(path)},
        "EDGE1": {"show vtp status": str(path)},
    }
    integrity = compute_capture_integrity_from_paths(aliases)

    unavailable = compute_vtp_safety_baseline(aliases, integrity)
    assert unavailable["projection_custody"] == "embedded_unverified"
    assert unavailable["verdict"] == "INDETERMINATE"
    assert validate_vtp_safety_baseline(
        unavailable, require_current_run=True)["valid"] is False
    assert scope_vtp_safety_subjects(aliases) == {
        "schema": "vtp_safety_subject_scope/1",
        "valid": False,
        "attempted": True,
        "reason": "scope_identity_collision",
        "rows": [],
    }
    assert compute_vtp_safety_subject_scope(aliases) == {
        "schema": "vtp_safety_subject_scope/1",
        "valid": False,
        "attempted": True,
        "reason": "scope_identity_collision",
        "rows": [],
    }

    first, _paths, _integrity = _owner(
        tmp_path / "first", _status(revision=1), host="edge1")
    second, _paths, _integrity = _owner(
        tmp_path / "second", _status(revision=2), host="edge2")
    forged = json.loads(json.dumps(first))
    second_plain = json.loads(json.dumps(second))
    forged["rows"].extend(second_plain["rows"])
    forged["coverage"].extend(second_plain["coverage"])
    forged["rows"][1]["switch"] = "EDGE1"
    forged["coverage"][1]["switch"] = "EDGE1"
    forged["coverage"][1]["source_sha256"] = vtp._sha(
        vtp._source_payload(forged["coverage"][1], forged["rows"][1]))
    forged["coverage"][1]["projection_sha256"] = vtp._sha(
        vtp._projection_payload(forged["coverage"][1], forged["rows"][1]))
    forged["summary"].update({
        "n_hosts": 2, "n_subject_hosts": 2, "n_rows": 2, "n_assessed": 2,
        "by_status": {"review": 0, "not_verified": 0, "assessed": 2},
        "by_coverage_status": {
            "review": 0, "not_verified": 0, "assessed": 2, "not_applicable": 0,
        },
    })
    forged["summary"]["baseline_sha256"] = ""
    forged["summary"]["baseline_sha256"] = vtp._sha(vtp._baseline_payload(forged))
    view = validate_vtp_safety_baseline(forged)
    assert view["valid"] is False
    assert view["reason"] == "baseline_row_identity_or_status_invalid"


def test_recursive_and_deep_hostile_values_are_validation_total(tmp_path: Path):
    baseline, _paths, _integrity = _owner(tmp_path, _status(revision=99))
    recursive = json.loads(json.dumps(baseline))
    recursive["limitations"].append(recursive["limitations"])

    nested: object = "leaf"
    for _index in range(2_000):
        nested = [nested]
    deep = json.loads(json.dumps(baseline))
    deep["findings"] = nested

    for hostile in (recursive, deep):
        view = validate_vtp_safety_baseline(hostile)
        assert view["valid"] is False
        assert view["rows"] == [] and view["baseline"] == {}


def test_resealed_boolean_census_and_impossible_neutral_source_are_rejected(tmp_path: Path):
    baseline, _paths, _integrity = _owner(tmp_path, _status(revision=99))
    forged = json.loads(json.dumps(baseline))
    forged["summary"]["n_hosts"] = True
    forged["summary"]["baseline_sha256"] = ""
    forged["summary"]["baseline_sha256"] = vtp._sha(vtp._baseline_payload(forged))
    assert validate_vtp_safety_baseline(forged)["reason"] == \
        "baseline_summary_census_invalid"

    neutral = compute_vtp_safety_baseline(
        {}, compute_capture_integrity_from_paths({}),
        devices={"edge1": {"platform": "ios-xe"}},
    )
    forged = json.loads(json.dumps(neutral))
    cell = forged["coverage"][0]
    cell["capture_status"] = "ok"
    cell["source_sha256"] = vtp._sha(vtp._source_payload(cell, None))
    cell["projection_sha256"] = vtp._sha(vtp._projection_payload(cell, None))
    forged["summary"]["baseline_sha256"] = ""
    forged["summary"]["baseline_sha256"] = vtp._sha(vtp._baseline_payload(forged))
    assert validate_vtp_safety_baseline(forged)["reason"] == \
        "baseline_coverage_no_subject_source_mismatch"


@pytest.mark.parametrize(
    ("paths", "integrity", "devices"),
    [
        (None, None, None),
        (42, {"inspections": "bad"}, {"edge": {"platform": "ios"}}),
        ({7: "bad", "edge": object()}, {"inspections": [None, 7, "bad"]}, object()),
    ],
)
def test_hostile_shapes_are_total_and_do_not_claim_assessment(
        paths: object, integrity: object, devices: object):
    baseline = compute_vtp_safety_baseline(paths, integrity, devices)

    assert baseline["verdict"] in {"NOT_APPLICABLE", "INDETERMINATE"}
    assert baseline["assessed"] is False
    assert validate_vtp_safety_baseline(baseline)["valid"] in {True, False}
