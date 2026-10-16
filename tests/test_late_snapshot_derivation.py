"""One late producer order, with preserved assessment failures and a bounded plan profile."""
from __future__ import annotations

import copy
import logging

import pytest

from cisco_toolkit import ssot


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
    ssot.derive_late_snapshot_sections(snapshot, {"availability_tier": "gold"}, profile=profile, **owners)
    assert failures == []
    if profile == "saved_plan":
        assert events == ["blueprint", "nrfu"]
        assert integrity == []
        assert snapshot["executive_brief"]["ssot"] == {"EXAMPLE_original": True}
        assert set(snapshot) == set(ssot.PLAN_SECTION_KEYS) | {"executive_brief"}
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
    ssot.derive_late_snapshot_sections(snapshot, {"availability_tier": "gold"}, profile="assessment", **owners)
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
        ssot.derive_late_snapshot_sections({}, {"availability_tier": "gold"}, profile="saved_plan", **owners)
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
    ssot.derive_late_snapshot_sections(snapshot, None, profile=profile, **owners)
    assert seen[0][1] is None
    if profile == "assessment":
        assert "requirements_register" not in seen[0][0] and "requirements_register" not in snapshot
    else:
        assert seen[0][0]["requirements_register"] == snapshot["requirements_register"] == {}


def test_unknown_profile_and_missing_assessment_callbacks_refuse_before_mutation():
    for profile in ("unknown", "assessment"):
        snapshot = {"EXAMPLE_original": True}
        with pytest.raises(ValueError):
            ssot.derive_late_snapshot_sections(snapshot, {}, profile=profile)
        assert snapshot == {"EXAMPLE_original": True}
