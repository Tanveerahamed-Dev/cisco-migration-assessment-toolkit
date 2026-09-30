"""SSOT owner robustness: four refuter-reported defects in ``cisco_toolkit/ssot.py``, each reproduced first.

1. ``reconcile()`` collected the health-row bands into a ``set``. A band that is not hashable (a list or a
   dict in a malformed or uploaded snapshot) raised ``TypeError``. Through ``ssot.summary()`` that aborted
   ``docmeta.add_excellence_front`` -- the front matter of every DOCX deliverable -- and the webapp's
   pre-emission SSOT gate (``ssot.audit`` under a broad ``except``) silently failed open.
2. ``_is_deep_empty()`` recursed once per nesting level, two interpreter frames per level: about 500
   levels of an uploaded section raised ``RecursionError`` out of ``abstention_reason()`` and
   ``compute_schema_census()``.
3. ``_INTEGRITY_META_KEYS`` lacked ``ssot_reconciliation``, the status key ``ssot.audit()`` itself
   discloses (value ``"failed"``, a failure token) and the producer merges into ``assessment_integrity``.
   ``failed_sections()`` then reported that metadata key as a failed SECTION.
4. ``fleet_avg_health()`` reported ``measured`` for a published average with no scored-row basis at all
   (``health_scores`` absent or not a list, and no usable ``posture.n_scored``): a number with no evidence
   that anything was scored. No in-repo producer writes that shape (the engine always writes the
   ``health_scores`` list, even the failed phase's ``[]``), and the pre-G15 producer's hard ``0`` over zero
   scored rows is indistinguishable from a measurement without the rows, so the value is ``unverified``.
"""
from __future__ import annotations

import ast
import json
import pathlib
import random
import sys

import pytest

from cisco_toolkit import ssot

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import COLLECT_PARSE_V3_23_0 as cp  # noqa: E402  (the producer owns the assessment_integrity writers)

ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
CBE = "collected_but_empty"
PUB = "published"


def _sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_the_module_under_test_is_this_checkout():
    """A standalone run can import an installed or sibling copy; every verdict below is about THIS file."""
    assert pathlib.Path(ssot.__file__).resolve().parent.parent == ROOT
    assert pathlib.Path(cp.__file__).resolve().parent == ROOT


# --------------------------------------------------------------------------------------------------
# 1. reconcile() is total over an unhashable health band
# --------------------------------------------------------------------------------------------------
UNHASHABLE_BANDS = ([], ["Critical"], {"band": "Critical"}, [[["Poor"]]], {})


@pytest.mark.parametrize("band", UNHASHABLE_BANDS, ids=["empty-list", "list", "dict", "nested", "empty-dict"])
def test_d1_an_unhashable_band_reads_like_any_other_unrecognised_band(band):
    """The fix may not invent a verdict: a band that is not a string is simply not a recognised band, the
    same as ``"Unrecognised"`` or ``7`` (which never crashed). Every ssot verdict over the real sample fleet
    must be identical between the two spellings -- violations, the checks that ran, the summary and the
    audit disclosure."""
    snap, twin = _sample(), _sample()
    snap["health_scores"][0]["band"] = band
    twin["health_scores"][0]["band"] = "Unrecognised"
    ran, ran_twin = [], []
    assert ssot.reconcile(snap, _ran=ran) == ssot.reconcile(twin, _ran=ran_twin)
    assert ran == ran_twin and ran                       # non-vacuous: the posture checks ran on both
    assert ssot.summary(snap) == ssot.summary(twin)
    assert ssot.audit(snap) == ssot.audit(twin)


def test_d1_worst_band_derivation_ignores_a_malformed_band():
    """A list that CONTAINS "Critical" is not the Critical band: the most-severe band present is Good."""
    rows = [{"switch": "a", "band": ["Critical"], "score": 10}, {"switch": "b", "band": "Good", "score": 80}]
    ok = {"health_scores": rows, "executive_brief": {"posture": {"worst_band": "Good"}}}
    assert ssot.reconcile(ok) == []
    bad = {"health_scores": rows, "executive_brief": {"posture": {"worst_band": "Critical"}}}
    assert ssot.reconcile(bad) == [
        "executive_brief.posture.worst_band='Critical' but most-severe band present='Good'"]


def test_d1_an_unhashable_published_worst_band_is_a_violation_not_a_crash():
    snap = {"health_scores": [{"switch": "a", "band": "Poor", "score": 40}],
            "executive_brief": {"posture": {"worst_band": ["Poor"]}}}
    assert ssot.reconcile(snap) == [
        "executive_brief.posture.worst_band=['Poor'] but most-severe band present='Poor'"]


def test_d1_every_docx_front_matter_survives_an_unhashable_band():
    """The consumer that crashed: ``docmeta.add_excellence_front`` calls ``ssot.summary`` unguarded."""
    from docx import Document

    from cisco_toolkit import docmeta
    snap = _sample()
    snap["health_scores"][0]["band"] = ["Critical"]
    doc = Document()
    docmeta.add_excellence_front(doc, snap)
    assert any(p.text.strip() for p in doc.paragraphs)


# --------------------------------------------------------------------------------------------------
# 2. _is_deep_empty() is iterative: any depth, identical semantics
# --------------------------------------------------------------------------------------------------
def _recursive_is_deep_empty(val):
    """The pre-fix definition, kept verbatim as the semantic oracle."""
    if isinstance(val, dict):
        return all(_recursive_is_deep_empty(v) for v in val.values())
    if isinstance(val, (list, tuple, set)):
        return all(_recursive_is_deep_empty(v) for v in val)
    return not val


def _nest(depth, leaf, kind):
    val = leaf
    for i in range(depth):
        val = {"k": val} if (kind == "dict" or (kind == "mixed" and i % 2)) else [val]
    return val


@pytest.mark.parametrize("depth", (500, 900, 5000, 50000))
@pytest.mark.parametrize("kind", ("list", "dict", "mixed"))
def test_d2_deep_empty_is_total_at_any_depth(depth, kind):
    assert ssot._is_deep_empty(_nest(depth, 0, kind)) is True
    assert ssot._is_deep_empty(_nest(depth, "evidence", kind)) is False
    # the evidence sits beside an empty sibling at the bottom: order of traversal cannot matter
    assert ssot._is_deep_empty(_nest(depth, [[], {"x": ""}, 1], kind)) is False


def test_d2_the_recursive_definition_really_failed_at_this_depth():
    """Non-vacuity for the depth tests above: the oracle itself cannot evaluate them."""
    with pytest.raises(RecursionError):
        _recursive_is_deep_empty(_nest(900, 0, "list"))


def test_d2_a_hostile_upload_reaches_the_abstention_core_and_the_census():
    """The refuter's reproduction: ~900 levels parsed by ``json.loads`` (the upload path)."""
    snap = json.loads('{"schema": "collect_parse_snapshot/1", "punchlist": ' + "[" * 900 + "]" * 900
                      + ', "qos_audit": ' + '{"a": ' * 900 + "1" + "}" * 900 + "}")
    assert ssot.abstention_reason(snap, "punchlist") == CBE
    assert ssot.abstention_reason(snap, "qos_audit") == PUB
    states = {r["key"]: r["state"] for r in ssot.compute_schema_census(snap)["sections"]}
    assert states == {"schema": PUB, "punchlist": CBE, "qos_audit": PUB}


_LEAVES = (0, 1, "", "x", None, False, True, 0.0, 2.5, frozenset(), frozenset({1}), b"", b"b")
_HASHABLE_LEAVES = tuple(v for v in _LEAVES if not isinstance(v, (list, dict, set)))


def _random_structure(rng, depth):
    if depth == 0 or rng.random() < 0.3:
        return rng.choice(_LEAVES)
    kind = rng.choice(("dict", "list", "tuple", "set"))
    n = rng.randint(0, 4)
    if kind == "set":
        return {rng.choice(_HASHABLE_LEAVES) for _ in range(n)} | (
            {tuple(_random_structure(rng, 0) for _ in range(2))} if rng.random() < 0.3 else set())
    items = [_random_structure(rng, depth - 1) for _ in range(n)]
    if kind == "dict":
        return {f"k{i}": v for i, v in enumerate(items)}
    return items if kind == "list" else tuple(items)


def test_d2_iterative_predicate_equals_the_recursive_definition():
    rng = random.Random(20260930)
    seen = {True: 0, False: 0}
    for _ in range(20000):
        val = _random_structure(rng, 5)
        want = _recursive_is_deep_empty(val)
        assert ssot._is_deep_empty(val) is want, val
        seen[want] += 1
    assert min(seen.values()) > 1000, seen                  # both verdicts exercised, not one


@pytest.mark.parametrize("val, want", [
    ({"dup_ip": [], "dup_subnet": []}, True),               # the documented wrapper-of-empties shape
    ({"dup_ip": [], "dup_subnet": [{"ip": "10.0.0.1"}]}, False),
    ([0, "", None, False, 0.0, [], {}, (), set()], True),
    ([0, 1], False),
    ({"a": {"b": [0, "x"]}}, False),
    ((), True), (set(), True), (frozenset({1}), False),     # a frozenset is a leaf, as before
    ("", True), ("0", False), (0, True), (None, True),
])
def test_d2_documented_cases(val, want):
    assert ssot._is_deep_empty(val) is want
    assert _recursive_is_deep_empty(val) is want


def test_d2_shared_and_self_referencing_containers_terminate():
    shared = [0, ""]
    assert ssot._is_deep_empty([shared, {"s": shared}]) is True
    assert ssot._is_deep_empty([shared, shared, 1]) is False
    loop = [0, ""]
    loop.append(loop)                                       # recursion never terminated on this
    assert ssot._is_deep_empty(loop) is True
    d = {"a": [], "x": 1}
    d["self"] = d
    assert ssot._is_deep_empty(d) is False


# --------------------------------------------------------------------------------------------------
# 3. assessment_integrity metadata is never a failed section
# --------------------------------------------------------------------------------------------------
def _drifting():
    return {"executive_brief": {"scale": {"n_devices": 5}}, "health_scores": [{"band": "Good", "score": 80}]}


def test_d3_the_producers_own_ssot_disclosure_is_not_a_failed_section():
    drift = ssot.audit(_drifting())
    assert drift and drift["ssot_reconciliation"] in ssot.INTEGRITY_FAILURE_TOKENS   # why it was misread
    snap = {}
    cp._record_ssot_integrity_failure(snap, drift)          # the real producer writer
    assert snap["assessment_integrity"]["ssot_reconciliation"] == "failed"
    assert ssot.failed_sections(snap) == (frozenset(), False)
    # ...and beside a real attributed failure, only the real section is direct
    snap["assessment_integrity"]["failed_phases"] = ["QoS audit"]
    snap["assessment_integrity"]["executive_brief"] = "compute_failed"
    assert ssot.failed_sections(snap) == (frozenset({"qos_audit", "executive_brief"}), False)


def test_d3_the_webapp_disclosure_copy_is_not_a_failed_section_either():
    from webapp.backend import deliverables
    rendered = deliverables._snapshot_with_ssot_disclosure({"health_scores": []}, ssot.audit(_drifting()))
    assert rendered["assessment_integrity"]["ssot_reconciliation"] == "failed"
    assert ssot.failed_sections(rendered) == (frozenset(), False)


def test_d3_every_key_audit_can_disclose_is_integrity_metadata():
    drift = ssot.audit(_drifting())
    assert set(drift) == set(ssot.AUDIT_DISCLOSURE_KEYS)
    assert set(ssot.AUDIT_DISCLOSURE_KEYS) <= ssot._INTEGRITY_META_KEYS


def test_d3_the_real_phase_failure_record_is_metadata(monkeypatch):
    snap = {}
    monkeypatch.setattr(cp, "_ACTIVE_INTEGRITY_SNAPSHOT", snap)
    cp._record_phase_failure("HTML Explorer", "RuntimeError: boom")    # a classified non-section phase
    assert set(snap["assessment_integrity"]) == {"failed_phases", "phase_errors"}
    assert set(snap["assessment_integrity"]) <= ssot._INTEGRITY_META_KEYS
    assert ssot.failed_sections(snap) == (frozenset(), False)


def test_d3_a_metadata_key_never_shadows_a_registered_section():
    sections = {s for secs in ssot.PHASE_SECTIONS.values() for s in secs}
    assert not (ssot._INTEGRITY_META_KEYS & sections)


def _integrity_writes():
    """Every string key the producer writes into ``assessment_integrity``, found structurally, plus the
    functions that merge a whole dict into it with ``.update``."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))

    def is_integrity_access(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
            first = node.args[0]
            return (node.func.attr in ("setdefault", "get") and isinstance(first, ast.Constant)
                    and first.value == "assessment_integrity")
        return (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == "assessment_integrity")

    keys, updaters = set(), set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        bound = set()                                      # names bound to (an expression over) the block
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(is_integrity_access(n) for n in ast.walk(node.value)):
                bound.update(t.id for t in node.targets if isinstance(t, ast.Name))

        def receiver(node):
            return is_integrity_access(node) or (isinstance(node, ast.Name) and node.id in bound)

        for node in ast.walk(fn):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    if (isinstance(t, ast.Subscript) and receiver(t.value) and isinstance(t.slice, ast.Constant)
                            and isinstance(t.slice.value, str)):
                        keys.add(t.slice.value)
                    if (isinstance(node, ast.Assign) and is_integrity_access(t)
                            and isinstance(node.value, ast.Dict)):
                        keys.update(k.value for k in node.value.keys
                                    if isinstance(k, ast.Constant) and isinstance(k.value, str))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and receiver(node.func.value):
                if (node.func.attr == "setdefault" and node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    keys.add(node.args[0].value)
                elif node.func.attr == "update":
                    updaters.add(fn.name)
    return keys, updaters


def test_d3_every_key_the_producer_writes_is_classified():
    """The meta-key list is hand-kept, so hold it complete against the producer: every literal key written
    into ``assessment_integrity`` is either failure metadata or a registered section stamp, and the only
    whole-dict merge is the SSOT disclosure (whose keys ``ssot.audit`` owns, checked above)."""
    keys, updaters = _integrity_writes()
    assert {"failed_phases", "phase_errors", "executive_brief", "architecture_review"} <= keys, keys  # non-vacuous
    sections = {s for secs in ssot.PHASE_SECTIONS.values() for s in secs}
    unclassified = keys - ssot._INTEGRITY_META_KEYS - sections
    assert not unclassified, f"assessment_integrity keys neither metadata nor a section: {sorted(unclassified)}"
    assert updaters == {"_record_ssot_integrity_failure"}, updaters


# --------------------------------------------------------------------------------------------------
# 4. fleet_avg_health(): a number with no scored-row basis is unverified, never measured
# --------------------------------------------------------------------------------------------------
_NO_BASIS = {"state": "unverified", "value": None, "n_scored": None, "n_rows": None, "reason": "no_scored_basis"}


@pytest.mark.parametrize("posture", [
    {"avg_health": 0},                                      # the pre-G15 hard 0 with its rows stripped
    {"avg_health": 72},
    {"avg_health": 72.5},
    {"avg_health": 0, "n_scored": True},                    # a bool is not a count
    {"avg_health": 50, "n_scored": -3},                     # nor is a negative number
    {"avg_health": 50, "n_scored": 2.0},
    {"avg_health": 50, "n_scored": "5"},
], ids=["legacy-zero", "int", "fraction", "bool-count", "negative-count", "float-count", "text-count"])
def test_d4_a_number_with_no_scored_row_basis_is_unverified(posture):
    assert ssot.fleet_avg_health({"executive_brief": {"posture": posture}}) == _NO_BASIS
    fh = ssot.fleet_avg_health({"health_scores": {"sw1": 1}, "executive_brief": {"posture": posture}})
    assert fh == _NO_BASIS                                   # a malformed (non-list) basis is no basis


def test_d4_a_non_number_is_still_named_as_such():
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": "abc"}}})
    assert (fh["state"], fh["value"], fh["reason"]) == ("unverified", None, "not_a_number")
    fh = ssot.fleet_avg_health({"health_scores": [{"band": "Good", "score": 80}],
                                "executive_brief": {"posture": {"avg_health": float("nan")}}})
    assert (fh["state"], fh["n_scored"], fh["reason"]) == ("unverified", 1, "not_a_number")


def test_d4_the_posture_count_still_stands_in_for_a_missing_list():
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": 80, "n_scored": 4}}})
    assert fh == {"state": "measured", "value": 80, "n_scored": 4, "n_rows": None, "reason": None}
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": None, "n_scored": 0}}})
    assert (fh["state"], fh["n_scored"], fh["reason"]) == ("not_assessed", 0, None)
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": 0, "n_scored": 0}}})
    assert fh["state"] == "not_assessed"                     # a number over a published zero is not measured


def test_d4_every_state_with_a_scored_row_basis_is_unchanged():
    sample = _sample()
    fh = ssot.fleet_avg_health(sample)
    assert fh["state"] == "measured" and fh["value"] == sample["executive_brief"]["posture"]["avg_health"]
    assert fh["n_scored"] and fh["n_rows"] == len(sample["health_scores"]) and fh["reason"] is None
    legacy = {"health_scores": [{"band": "Insufficient Data", "score": 100}] * 3,
              "executive_brief": {"posture": {"avg_health": 0}}}
    assert (ssot.fleet_avg_health(legacy)["state"], ssot.fleet_avg_health(legacy)["n_scored"]) == ("not_assessed", 0)
    empty = {"health_scores": [], "executive_brief": {"posture": {"avg_health": 0}}}
    assert ssot.fleet_avg_health(empty)["state"] == "not_assessed"    # zero rows is a basis: zero scored
    for snap in ({}, None, {"executive_brief": {"_unavailable": True, "posture": {"avg_health": 80}}},
                 {"executive_brief": {"posture": {}}}):
        assert ssot.fleet_avg_health(snap) == {"state": "unpublished", "value": None, "n_scored": None,
                                               "n_rows": None, "reason": None}


def test_d4_a_stripped_legacy_zero_is_no_longer_rendered_as_a_measurement():
    """The consumer view of the defect: the At-a-Glance row printed "average health 0/100"."""
    from cisco_toolkit import docmeta
    snap = {"executive_brief": {"posture": {"avg_health": 0, "n_critical": 0, "n_poor": 0, "worst_band": ""}}}
    health = dict(docmeta._glance_rows(snap))["How healthy is the fleet?"]
    assert "UNVERIFIED" in health and "0/100" not in health, health


def test_d4_the_withheld_reason_vocabulary_is_closed():
    reasons = {ssot.fleet_avg_health(s)["reason"] for s in (
        _sample(), {}, {"executive_brief": {"posture": {"avg_health": None, "n_scored": 0}}},
        {"executive_brief": {"posture": {"avg_health": "abc"}}}, {"executive_brief": {"posture": {"avg_health": 7}}})}
    assert reasons == {None} | set(ssot.FLEET_AVG_UNVERIFIED_REASONS)
    assert ssot.FLEET_AVG_UNVERIFIED_REASONS == ("not_a_number", "no_scored_basis")
