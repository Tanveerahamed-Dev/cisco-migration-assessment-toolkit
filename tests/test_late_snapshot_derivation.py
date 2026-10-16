"""Shared plan prefix and the actual CLI late blocks, executed only by hosted pytest."""
from __future__ import annotations

import ast
import copy
import logging
from pathlib import Path

import pytest

from cisco_toolkit import design_advisor, ssot


_LATE_FAILURES = ("Design blueprint", "Unknown evidence", "SSOT self-check", "Schema census / fact lineage")


def _run_cli_late_blocks(snapshot, requirements, owners):
    """Exercise complete production Try nodes without running collection or the full engine.

    The selected nodes include their original handlers/else/finally bodies. Fake owner
    functions make their order and failure boundaries observable; no production block is
    re-created in this test. Imports inside the nodes resolve the real (patched) modules.
    """
    path = Path(__file__).resolve().parents[1] / "COLLECT_PARSE_V3_23_0.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    blocks, labels, positions = [], [], []
    for position, statement in enumerate(main.body):
        if not isinstance(statement, ast.Try):
            continue
        found = [node.args[0].value for handler in statement.handlers for node in ast.walk(handler)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == "_record_phase_failure" and node.args
                 and isinstance(node.args[0], ast.Constant) and node.args[0].value in _LATE_FAILURES]
        if found:
            assert len(found) == 1
            blocks.append(statement)
            labels.extend(found)
            positions.append(position)
    assert tuple(labels) == _LATE_FAILURES, "must extract all four production failure boundaries in order"
    assert positions == list(range(positions[0], positions[0] + 4)), "late groups must remain contiguous"
    calls = [node for node in ast.walk(blocks[0]) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "_design_advisor" and node.func.attr == "derive_plan_sections"]
    assert len(calls) == 1 and isinstance(calls[0].args[0], ast.Name) and calls[0].args[0].id == "snap_dict"
    assert any(keyword.arg == "profile" and isinstance(keyword.value, ast.Constant)
               and keyword.value.value == "assessment" for keyword in calls[0].keywords)
    module = ast.parse("def _selected_cli_late():\n    pass\n")
    module.body[0].body = copy.deepcopy(blocks)
    ast.fix_missing_locations(module)
    scope = {
        "snap_dict": snapshot, "_validated_inputs": {"requirements": requirements},
        "compute_design_blueprint": owners["compute_blueprint"],
        "compute_design_nrfu": owners["compute_nrfu"],
        "compute_architecture_coverage": owners["compute_architecture"],
        "compute_coverage_matrix": owners["compute_coverage"],
        "compute_unknown_evidence": owners["compute_unknown"],
        "unavailable_unknown_evidence": owners["unknown_unavailable"],
        "logger": owners["logger"], "_record_phase_failure": owners["record_phase_failure"],
        "_record_ssot_integrity_failure": owners["record_integrity_failure"],
        "wb": object(), "write_coverage_schema_sheet": lambda _wb, census: owners["publish_schema"](census),
    }
    exec(compile(module, str(path), "exec"), scope)
    scope["_selected_cli_late"]()


def _run_profile(snapshot, requirements, profile, owners):
    if profile == "assessment":
        _run_cli_late_blocks(snapshot, requirements, owners)
    else:
        design_advisor.derive_plan_sections(
            snapshot, requirements, profile=profile,
            compute_blueprint=owners["compute_blueprint"], compute_nrfu=owners["compute_nrfu"],
        )


def _owners(monkeypatch, *, fail=None):
    events, failures, integrity = [], [], []
    census_calls = 0

    def enter(name):
        events.append(name)
        if name == fail:
            raise RuntimeError("EXAMPLE phase refusal")

    def blueprint(snapshot, requirements):
        enter("blueprint")
        assert snapshot["requirements_register"] == {"availability_tier": "gold"}
        assert requirements is snapshot["requirements_register"]
        return {"decisions": [], "EXAMPLE_stage": "blueprint"}

    def nrfu(design):
        enter("nrfu")
        assert design["EXAMPLE_stage"] == "blueprint"
        return {"items": [], "EXAMPLE_stage": "nrfu"}

    def architecture(snapshot):
        enter("architecture")
        assert snapshot["design_nrfu"]["EXAMPLE_stage"] == "nrfu"
        return {"EXAMPLE_stage": "architecture"}

    def coverage(snapshot):
        enter("coverage")
        assert snapshot["architecture_coverage"]["EXAMPLE_stage"] == "architecture"
        return {"EXAMPLE_stage": "coverage"}

    def unknown(_snapshot):
        enter("unknown")
        return {"EXAMPLE_stage": "unknown"}

    def unavailable():
        enter("unavailable")
        return {"state": "unavailable"}

    def audit(_snapshot):
        enter("audit")
        return {"ssot_reconciliation": "failed", "violations": ["EXAMPLE drift"]}

    def summary(_snapshot):
        enter("summary")
        return {"verified": False}

    def record_integrity(snapshot, drift):
        enter("integrity")
        assert snapshot["executive_brief"]["ssot"] == {"verified": False}
        integrity.append(copy.deepcopy(drift))
        snapshot.setdefault("assessment_integrity", {}).update(drift)

    def census(snapshot):
        nonlocal census_calls
        census_calls += 1
        enter("census" if census_calls == 1 else "recensus")
        if census_calls == 2:
            assert "schema_census" in snapshot and "fact_lineage" in snapshot
        return {"summary": {"n_sections": len(snapshot)}, "EXAMPLE_pass": census_calls}

    def lineage(snapshot):
        enter("lineage")
        assert snapshot["schema_census"]["EXAMPLE_pass"] == 1
        return {"facts": []}

    def publish(census):
        enter("sheet")
        assert census["EXAMPLE_pass"] == 2

    def record_failure(label, detail):
        failures.append((label, detail))

    monkeypatch.setattr(ssot, "audit", audit)
    monkeypatch.setattr(ssot, "summary", summary)
    monkeypatch.setattr(ssot, "compute_schema_census", census)
    monkeypatch.setattr(ssot, "compute_fact_lineage", lineage)
    return events, failures, integrity, {
        "compute_blueprint": blueprint, "compute_nrfu": nrfu,
        "compute_architecture": architecture, "compute_coverage": coverage,
        "compute_unknown": unknown, "unknown_unavailable": unavailable,
        "logger": logging.getLogger("EXAMPLE-late-derivation"),
        "record_phase_failure": record_failure,
        "record_integrity_failure": record_integrity, "publish_schema": publish,
    }


@pytest.mark.parametrize("profile", ["assessment", "saved_plan"])
def test_shared_prefix_and_exact_full_assessment_order(profile, monkeypatch):
    events, failures, integrity, owners = _owners(monkeypatch)
    snapshot = {"executive_brief": {"ssot": {"EXAMPLE_original": True}}}
    _run_profile(snapshot, {"availability_tier": "gold"}, profile, owners)
    assert failures == []
    if profile == "saved_plan":
        assert events == ["blueprint", "nrfu"]
        assert integrity == []
        assert snapshot["executive_brief"]["ssot"] == {"EXAMPLE_original": True}
        assert set(snapshot) == set(design_advisor.PLAN_SECTION_KEYS) | {"executive_brief"}
    else:
        assert events == ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit",
                          "summary", "integrity", "census", "lineage", "recensus", "sheet"]
        assert len(integrity) == 1
        assert snapshot["schema_census"]["EXAMPLE_pass"] == 2


@pytest.mark.parametrize("failed,phase,expected", [
    ("blueprint", "Design blueprint", ["blueprint", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
    ("nrfu", "Design blueprint", ["blueprint", "nrfu", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
    ("architecture", "Design blueprint", ["blueprint", "nrfu", "architecture", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
    ("coverage", "Design blueprint", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
    ("unknown", "Unknown evidence", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "unavailable", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
    ("audit", "SSOT self-check", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "census", "lineage", "recensus", "sheet"]),
    ("summary", "SSOT self-check", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "census", "lineage", "recensus", "sheet"]),
    ("integrity", "SSOT self-check", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
    ("census", "Schema census / fact lineage", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "integrity", "census"]),
    ("lineage", "Schema census / fact lineage", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "integrity", "census", "lineage"]),
    ("recensus", "Schema census / fact lineage", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus"]),
    ("sheet", "Schema census / fact lineage", ["blueprint", "nrfu", "architecture", "coverage", "unknown", "audit", "summary", "integrity", "census", "lineage", "recensus", "sheet"]),
], ids=lambda value: value if isinstance(value, str) else None)
def test_assessment_preserves_four_failure_boundaries_and_partial_publication(failed, phase, expected, monkeypatch, caplog):
    events, failures, _integrity, owners = _owners(monkeypatch, fail=failed)
    snapshot = {"executive_brief": {"ssot": {"EXAMPLE_original": True}}}
    _run_profile(snapshot, {"availability_tier": "gold"}, "assessment", owners)
    assert events == expected
    assert failures == [(phase, "RuntimeError: EXAMPLE phase refusal")]
    assert "non-fatal" in caplog.text and "EXAMPLE phase refusal" in caplog.text
    if failed == "unknown":
        assert snapshot["unknown_evidence"] == {"state": "unavailable"}
    if failed == "nrfu":
        assert snapshot["design_blueprint"]["EXAMPLE_stage"] == "blueprint"
        assert "design_nrfu" not in snapshot and "architecture_coverage" not in snapshot
    if failed == "recensus":
        assert snapshot["schema_census"]["EXAMPLE_pass"] == 1 and "fact_lineage" in snapshot


@pytest.mark.parametrize("failed", ["blueprint", "nrfu"])
def test_saved_plan_profile_propagates_failure_without_assessment_fallback(failed, monkeypatch):
    events, failures, integrity, owners = _owners(monkeypatch, fail=failed)
    with pytest.raises(RuntimeError, match="EXAMPLE phase refusal"):
        _run_profile({}, {"availability_tier": "gold"}, "saved_plan", owners)
    assert events == (["blueprint"] if failed == "blueprint" else ["blueprint", "nrfu"])
    assert failures == [] and integrity == []


@pytest.mark.parametrize("profile", ["assessment", "saved_plan"])
def test_empty_requirements_preserve_cli_absence_but_replace_plan_register(profile, monkeypatch):
    _events, _failures, _integrity, owners = _owners(monkeypatch)
    seen = []

    def blueprint(snapshot, requirements):
        seen.append((copy.deepcopy(snapshot), requirements))
        return {"EXAMPLE_stage": "blueprint"}

    owners["compute_blueprint"] = blueprint
    snapshot = {"executive_brief": {}}
    if profile == "saved_plan":
        snapshot["requirements_register"] = {"constraints": ["EXAMPLE original intent"]}
    _run_profile(snapshot, None, profile, owners)
    assert seen[0][1] is None
    if profile == "assessment":
        assert "requirements_register" not in seen[0][0] and "requirements_register" not in snapshot
    else:
        assert seen[0][0]["requirements_register"] == snapshot["requirements_register"] == {}


def test_unknown_profile_and_missing_assessment_callbacks_refuse_before_mutation():
    for profile in ("unknown", "assessment"):
        snapshot = {"EXAMPLE_original": True}
        with pytest.raises(ValueError):
            design_advisor.derive_plan_sections(snapshot, {}, profile=profile)
        assert snapshot == {"EXAMPLE_original": True}


def test_actual_cli_logs_supplied_requirements_before_blueprint_failure(monkeypatch, caplog):
    events, failures, _integrity, owners = _owners(monkeypatch, fail="blueprint")
    with caplog.at_level(logging.INFO, logger=owners["logger"].name):
        _run_cli_late_blocks({"executive_brief": {}}, {"availability_tier": "gold"}, owners)
    messages = [record.getMessage() for record in caplog.records if record.name == owners["logger"].name]
    assert messages[:2] == [
        "  [design] requirements register supplied (availability_tier) -> blueprint right-sized",
        "  design_blueprint compute failed (non-fatal): EXAMPLE phase refusal",
    ]
    assert events[0] == "blueprint" and failures == [("Design blueprint", "RuntimeError: EXAMPLE phase refusal")]
