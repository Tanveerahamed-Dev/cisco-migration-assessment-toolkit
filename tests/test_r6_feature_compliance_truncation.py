"""A DISPLAY cap in the producer must never become a compliance verdict in the consumer.

`compute_golden_drift` stores `per_device[].missing = missing[:30]` (analyze.py) while `n_missing`
keeps the TRUE count — the cap is a snapshot-size bound, and every RENDERER of that field re-caps at
display time anyway (runbook.py §6.9 renders 6 of them beside the true `n_missing`).

`compute_feature_compliance` consumes the same field as DATA. It groups the visible directives by
feature and grades each feature `compliant` when its group is empty — so a feature whose missing
directives all fell past the producer's cut was graded compliant on no evidence at all.

**In majority mode this is systematic, not occasional.** The producer builds
`baseline = sorted(line for line, c in freq.items() if c >= thr)`, so `missing` is alphabetically
ordered and the survivors are the alphabetically-FIRST 30. A late-sorting feature (`spanning-tree`,
`snmp`, `vlan`, `services`) is therefore dropped on *every* device over the cap, and graded
compliant on every one of them.

Found by a truncation sweep that measured 57 of 212 real rows where `len(missing) < n_missing`
(worst: 47 true vs 30 stored). The cap lives in one module and the false verdict in another, which is
why no single-file review had connected them.
"""

from __future__ import annotations

from cisco_toolkit.feature_compliance import compute_feature_compliance

# 30 `aaa …` directives sort ahead of 5 `spanning-tree …` ones, so the producer's 30-cap keeps every
# aaa line and drops the whole spanning-tree feature — the exact shape measured on real data.
_BASELINE = sorted(
    [f"aaa group server radius GRP{i:02d}" for i in range(30)]
    + [f"spanning-tree vlan {v} priority 8192" for v in (10, 20, 30, 40, 50)]
)


def _row(out, feature):
    return next(r for r in out["per_device_feature"] if r["feature"] == feature)


def _drift(name, missing, n_missing):
    return {"baseline": _BASELINE,
            "per_device": [{"host": "sw1", "compliance_pct": 0,
                            "n_missing": n_missing, "missing": missing}]}


def test_a_feature_lost_to_the_producers_cap_is_not_graded_compliant():
    """The defect: 5 of 5 spanning-tree directives missing, all past the cut, graded `compliant`."""
    capped = _drift("sw1", _BASELINE[:30], len(_BASELINE))       # what analyze.py actually stores
    out = compute_feature_compliance(capped)

    stp = _row(out, "spanning-tree")
    assert stp["status"] != "compliant", (
        "a feature with NO visible evidence on a truncated device was graded compliant")
    assert stp["status"] == "not-assessable"
    assert out["summary"]["n_unassessable_rows"] >= 1

    # aaa IS visible and still drifts — the abstention must not swallow evidence we have.
    assert _row(out, "aaa")["status"] == "drift"
    assert out["summary"]["n_drift_rows"] >= 1


def test_the_uncapped_truth_is_what_the_abstention_stands_in_for():
    """Establishes that the capped verdict was WRONG, not merely cautious: given the full list, this
    device genuinely drifts on spanning-tree."""
    full = _drift("sw1", list(_BASELINE), len(_BASELINE))
    assert _row(compute_feature_compliance(full), "spanning-tree")["status"] == "drift"


def test_an_untruncated_device_still_grades_compliant():
    """Refute the fix: with nothing dropped, a clean feature must still read compliant — otherwise
    this is a blanket demotion that would make every compliant grade meaningless."""
    clean = _drift("sw1", [], 0)
    out = compute_feature_compliance(clean)
    assert _row(out, "spanning-tree")["status"] == "compliant"
    assert _row(out, "aaa")["status"] == "compliant"
    assert out["summary"]["n_unassessable_rows"] == 0


def test_a_partially_truncated_device_still_reports_the_drift_it_can_see():
    """The middle case: some evidence visible for a feature, the list truncated overall. Visible
    drift stays drift — truncation only governs features with nothing to show."""
    visible = [b for b in _BASELINE if b.startswith("spanning-tree")][:2]
    out = compute_feature_compliance(_drift("sw1", visible, 40))
    assert _row(out, "spanning-tree")["status"] == "drift"
    assert _row(out, "aaa")["status"] == "not-assessable"


def test_a_malformed_n_missing_cannot_manufacture_a_truncation():
    """`n_missing` is untrusted input like anything else on a snapshot. A non-numeric value must fall
    back to what is visible rather than mark every feature unassessable (which would be its own
    coverage lie, in the cautious direction)."""
    for bad in (None, "many", {}, [], True):
        out = compute_feature_compliance(_drift("sw1", [], bad))
        assert _row(out, "spanning-tree")["status"] == "compliant", f"n_missing={bad!r}"
        assert out["summary"]["n_unassessable_rows"] == 0, f"n_missing={bad!r}"
