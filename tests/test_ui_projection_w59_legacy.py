"""W59 PR-1 review (supervisor P2): a snapshot whose producer predates the SSH session disclosure keeps its projection.

PR-1 added ``ssh_sessions`` to ``ui_projection.PUNCHLIST_INPUTS`` (the Findings list, its total and every device finding
rollup roll up over it) and ``software_risk``'s derived basis (``ssot.DERIVED_FACT_BASIS``). Read naively, a snapshot
written before the engine had that section -- every stored pre-W59 AssessHub or Atlas snapshot -- lacks an input, and
every one of those values turned ``not_collected``. A producer that predates a section is not a failed phase.

``ui_projection._Ctx.predates`` reads the snapshot's OWN version signal: its embedded census (``schema_census``), which
every producer since J3 writes over its final section set. A readable census that lists no ``ssh_sessions`` proves the
producer never wrote it. A failed phase (attributed even when the section is absent), an owner fault, a present null,
and an absence the census cannot explain (it lists the section, is missing, failed, is of another schema, or holds a row
that cannot be read) still propagate.

The pre-W59 snapshot is REAL: ``tests/fixtures/pre_w59_golden_snapshot.json`` is a byte copy of the engine's own golden
snapshot as ``main`` carried it before W59 (``tests/golden/snapshot.json`` at ``ddac90e3``, git blob ``2fe78dd8``),
frozen here because the hosted regeneration gives the live golden its ``ssh_sessions`` block.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cisco_toolkit import analyze, ssot
from cisco_toolkit import ui_projection as U

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pre_w59_golden_snapshot.json"
#: SHA-256 of the fixture's bytes with LF line ends (a Windows checkout may smudge them to CRLF).
FIXTURE_SHA256 = "c4f6a549299bd6494b9b0377a7a5be773d2322b3ace3b785701d2a57e7cc4643"
AU, NC, PUB = "analysis_unavailable", "not_collected", "published"


def _pre_w59():
    raw = FIXTURE.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256, "the frozen pre-W59 snapshot changed"
    return json.loads(raw.decode("utf-8"))


def _everything(snap):
    """The whole projection of a snapshot: the fleet document and every device's document."""
    return json.dumps({"project": U.project(copy.deepcopy(snap)),
                       "devices": U.project_devices(copy.deepcopy(snap), sorted(snap["devices"]))},
                      sort_keys=True, default=str)


def _findings(snap):
    doc = U.project_findings(copy.deepcopy(snap))
    return doc["findings"] if "findings" in doc else doc


def _rollups(snap):
    return {host: U.project_device(copy.deepcopy(snap), host)["device"]["findings_rollup"]
            for host in sorted(snap["devices"])}


def test_the_fixture_is_a_real_pre_w59_producer_snapshot():
    snap = _pre_w59()
    census = {row["key"] for row in snap["schema_census"]["sections"]}
    assert "ssh_sessions" not in snap and "ssh_sessions" not in census
    assert snap["schema_census"]["schema"] == ssot.SCHEMA_CENSUS_SCHEMA and "punchlist" in census
    assert U._Ctx(snap).predates("ssh_sessions") and not U._Ctx(snap).uncollected("ssh_sessions")


def test_a_pre_w59_snapshot_projects_exactly_as_before_w59(monkeypatch):
    """The supervisor's P2. Catches: the Findings list, its total, every device finding rollup and the Software risk
    facts of a stored pre-W59 snapshot withheld as not_collected because W59 added ``ssh_sessions`` to their inputs.
    With the W59 registrations in place, the WHOLE projection equals the projection without them."""
    snap = _pre_w59()
    findings = _findings(snap)
    assert findings["rows"]["state"] == PUB and findings["total"]["state"] == PUB
    assert {cell["state"] for roll in _rollups(snap).values() for cell in roll.values()} >= {PUB}
    with_w59 = _everything(snap)
    monkeypatch.setattr(U, "PUNCHLIST_INPUTS", tuple(s for s in U.PUNCHLIST_INPUTS if s != "ssh_sessions"))
    monkeypatch.setattr(ssot, "DERIVED_FACT_BASIS",
                        {k: v for k, v in ssot.DERIVED_FACT_BASIS.items() if k != "software_risk"})
    assert _everything(snap) == with_w59


def test_without_the_version_signal_the_regression_returns(monkeypatch):
    """Falsifier for the test above: with the census reading disabled, the same pre-W59 snapshot loses its Findings
    list, total and device rollups to not_collected -- the regression this module pins away."""
    snap = _pre_w59()
    monkeypatch.setattr(U._Ctx, "predates", lambda self, section: False)
    findings = _findings(snap)
    assert findings["rows"]["state"] == NC and "ssh_sessions" in findings["rows"]["reason"]
    assert findings["total"]["state"] == NC
    assert all(cell["state"] != PUB for roll in _rollups(snap).values() for cell in roll.values())


@pytest.mark.parametrize("present", [False, True], ids=["section-absent", "fallback-present"])
def test_a_failed_ssh_session_phase_still_propagates(present):
    """A failed 'SSH session disclosure' phase is NOT a predating producer: the Findings list, its total and every
    device rollup are analysis_unavailable, whether the fallback ``{}`` is stored or the section is absent."""
    snap = _pre_w59()
    label = next(lab for lab, secs in ssot.PHASE_SECTIONS.items() if "ssh_sessions" in secs)
    snap["assessment_integrity"] = {"failed_phases": [label]}
    if present:
        snap["ssh_sessions"] = {}
    assert not U._Ctx(snap).predates("ssh_sessions")
    findings = _findings(snap)
    assert findings["rows"]["state"] == AU and findings["total"]["state"] == AU
    assert {cell["state"] for roll in _rollups(snap).values() for cell in roll.values()} == {AU}


def _census_lists_it(snap):
    snap["schema_census"]["sections"].append(
        {"key": "ssh_sessions", "state": "published", "count": 3, "kind": "dict", "note": "seen"})


def _no_census(snap):
    snap.pop("schema_census")


def _other_schema(snap):
    snap["schema_census"]["schema"] = "schema_census/2"


def _unreadable_row(snap):
    snap["schema_census"]["sections"].append({"key": ["ssh_sessions"]})


def _census_failed(snap):
    snap["assessment_integrity"] = {"failed_phases": ["Schema census / fact lineage"]}


def _present_null(snap):
    snap["ssh_sessions"] = None


@pytest.mark.parametrize("mutate", [_census_lists_it, _no_census, _other_schema, _unreadable_row, _present_null],
                         ids=lambda f: f.__name__.strip("_"))
def test_an_absence_the_census_cannot_explain_stays_not_collected(mutate):
    """Catches: any absence of ``ssh_sessions`` read as a predating producer. The census lists the section (it was
    written, then removed), there is no census, a census of another schema, a census row whose key cannot be read, or
    the engine wrote null: the Findings list stays withheld as not_collected."""
    snap = _pre_w59()
    mutate(snap)
    assert not U._Ctx(snap).predates("ssh_sessions")
    findings = _findings(snap)
    assert findings["rows"]["state"] == NC and "ssh_sessions" in findings["rows"]["reason"]


def test_a_failed_census_is_no_version_signal():
    snap = _pre_w59()
    _census_failed(snap)
    assert not U._Ctx(snap).predates("ssh_sessions")


def test_the_registry_is_exactly_what_a_pre_w59_producer_lacks():
    """``LATER_INPUT_SECTIONS`` is not a hand-kept list standing in for its class: it equals the rollup and derived-basis
    inputs the real pre-W59 producer's census does not list. A section added to an input tuple later must be
    registered (or it would withhold every older snapshot), and a registered one that every older snapshot carries is
    no later section."""
    census = {row["key"] for row in _pre_w59()["schema_census"]["sections"]}
    inputs = (set(U.PUNCHLIST_INPUTS) | set(U.BRIEF_INPUTS) | set(U.CROSS_LAYER_INPUTS) | set(U.READINESS_INPUTS)
              | {s for secs in U.TRUST_INPUTS.values() for s in secs}
              | {s for secs in ssot.DERIVED_FACT_BASIS.values() for s in secs})
    assert inputs - census == set(U.LATER_INPUT_SECTIONS)
    assert not U._Ctx(_pre_w59()).predates("security")          # only a registered section can predate


def test_a_dossier_recomputed_over_a_pre_w59_snapshot_keeps_its_software_axis():
    """The same P2 on the dossier side (AssessHub recomputes the risk register with ``ssh_sessions=snap.get(...)``):
    with an unattributed failure recorded, ``ssh_sessions=None`` is NOT SUPPLIED, never a failed phase's fallback, so
    the Software risk axis is not withheld for it -- while a stored fallback ``{}`` still is."""
    snap = _pre_w59()
    kwargs = dict(software_risk=snap["software_risk"], input_failures=(frozenset(), True))
    legacy = analyze.compute_device_dossiers(**kwargs)
    axes = [e for row in legacy["per_device"] for e in row["exposures"] if e["axis"] == "Software risk"]
    assert axes and all(e["input_state"] != AU for e in axes), axes
    fallback = analyze.compute_device_dossiers(**kwargs, ssh_sessions={})
    axes = [e for row in fallback["per_device"] for e in row["exposures"] if e["axis"] == "Software risk"]
    assert axes and all(e["input_state"] == AU for e in axes), axes
