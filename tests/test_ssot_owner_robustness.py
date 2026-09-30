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

Round 2 -- the independent refuters of that fix, each finding reproduced here before it was fixed:

* ``reconcile()`` still raised ``OverflowError`` on two finite scores whose float sum overflows (valid JSON).
* A health row whose band is outside the producer's vocabulary left the band facts "verified" (``summary()``
  said ``verified: True`` over rows whose band nobody could read).
* A positive ``posture.n_scored`` (never written by the engine, which publishes it only as the abstention's
  ``0``) vouched for an average with no rows; ``False`` / ``0.0`` were read as that zero.
* The abstention core called the posture facts of a snapshot with no ``health_scores`` list ``published``
  (``collected_but_empty`` for a stripped zero) while ``fleet_avg_health`` withholds them, and
  ``summary()`` counted them -- and an ``unverified`` average -- among its "self-verified" figures.
* ``_is_deep_empty`` remembered containers by ``id()`` without holding them, so a freed child's id could be
  reused and a populated section read as empty.
* ``str()`` / ``repr()`` of a hostile nesting (a phase label, a posture value, a VRF name) and a non-string
  host / device still raised out of ``failed_sections``, ``reconcile``, ``segmentation_facts`` and
  ``abstention_reason``; a non-dict snapshot raised out of ``reconcile`` / ``audit`` / ``summary``.
* The producer-key scan covered one file; it now covers every first-party Python file.
"""
from __future__ import annotations

import ast
import json
import pathlib
import random
import re
import shutil
import subprocess
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


def test_d1_a_malformed_band_is_never_read_as_the_band_it_contains():
    """A list that CONTAINS "Critical" is not the Critical band -- and it is not readable as any other band
    either, so the most-severe band present cannot be determined (round 2: never "verified" over it)."""
    rows = [{"switch": "a", "band": ["Critical"], "score": 10}, {"switch": "b", "band": "Good", "score": 80}]
    for published in ("Good", "Critical"):
        snap = {"health_scores": rows, "executive_brief": {"posture": {"worst_band": published}}}
        assert ssot.reconcile(snap) == [
            f"executive_brief.posture.worst_band={published!r} but 1 health row(s) carry no recognised band, "
            f"so the most-severe band present cannot be determined"]


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


def _first_party_python():
    """Every first-party Python source that is not a test: tracked plus untracked-not-ignored files. If git
    cannot answer, the glob is WIDER, not narrower -- over-reporting is recoverable, silently looking at
    nothing is not (the same fallback tests/test_gate_state.py uses)."""
    try:
        out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z", "--", "*.py"],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=60, check=True).stdout
        paths = [ROOT / n for n in out.split("\0") if n]
    except Exception:
        paths = []
    paths = paths or list(ROOT.glob("**/*.py"))
    return [p for p in paths if "tests" not in p.relative_to(ROOT).parts[:-1] and p.is_file()]


def _integrity_writes(path=ENGINE):
    """Every string key one source file writes into ``assessment_integrity``, found structurally, plus the
    functions that merge a whole dict into it (an ``.update`` on it, or a non-literal assigned to it)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

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
                    if isinstance(node, ast.Assign) and is_integrity_access(t):
                        if isinstance(node.value, ast.Dict):
                            keys.update(k.value for k in node.value.keys
                                        if isinstance(k, ast.Constant) and isinstance(k.value, str))
                        else:
                            updaters.add(fn.name)          # a whole dict built elsewhere lands in the slot
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


def test_r2_no_first_party_file_writes_an_unclassified_integrity_key():
    """Round 2: the scan above covered the one producer file, so a writer added anywhere else (the webapp,
    a portable tool, a new module) was unchecked. Every first-party, non-test Python file is scanned; the
    whole-dict mergers are exactly the two that merge ``ssot.audit()``'s disclosure (both exercised above)."""
    sections = {s for secs in ssot.PHASE_SECTIONS.values() for s in secs}
    files = _first_party_python()
    assert ENGINE in files and ROOT / "webapp" / "backend" / "deliverables.py" in files      # non-vacuous
    unclassified, mergers = {}, set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "assessment_integrity" not in text:
            continue
        keys, updaters = _integrity_writes(path)
        rel = path.relative_to(ROOT).as_posix()
        mergers.update((rel, fn) for fn in updaters)
        bad = keys - ssot._INTEGRITY_META_KEYS - sections
        if bad:
            unclassified[rel] = sorted(bad)
    assert not unclassified, f"assessment_integrity keys neither metadata nor a section: {unclassified}"
    assert mergers == {("COLLECT_PARSE_V3_23_0.py", "_record_ssot_integrity_failure"),
                       ("webapp/backend/deliverables.py", "_snapshot_with_ssot_disclosure")}, mergers


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


def test_d4_only_the_producers_abstention_count_stands_in_for_a_missing_list():
    """The engine publishes ``posture.n_scored`` ONLY on its abstention, and only as ``0``
    (analyze.compute_executive_brief). That record stands in for a missing list; a positive count is no
    engine output, and a count vouching for itself is no scored-row basis (round 2: it was ``measured``)."""
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": None, "n_scored": 0}}})
    assert (fh["state"], fh["n_scored"], fh["reason"]) == ("not_assessed", 0, None)
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": 0, "n_scored": 0}}})
    assert fh["state"] == "not_assessed"                     # a number over a published zero is not measured


@pytest.mark.parametrize("n", [1, 4, 10 ** 30])
def test_r2_a_positive_posture_count_is_no_scored_row_basis(n):
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": 80, "n_scored": n}}})
    assert fh == _NO_BASIS
    # with the rows present the rows decide, exactly as before
    rows = [{"band": "Good", "score": 80}]
    fh = ssot.fleet_avg_health({"health_scores": rows, "executive_brief": {"posture": {"avg_health": 80,
                                                                                          "n_scored": n}}})
    assert (fh["state"], fh["value"], fh["n_scored"]) == ("measured", 80, 1)


@pytest.mark.parametrize("fake_zero", [False, 0.0, "0"], ids=["bool", "float", "text"])
def test_r2_only_an_integer_zero_is_the_abstention_record(fake_zero):
    """``False == 0`` and ``0.0 == 0`` in Python, so a bool / float read as the producer's zero: "a bool is not
    a count" held for the stand-in but not for the abstention test beside it."""
    fh = ssot.fleet_avg_health({"executive_brief": {"posture": {"avg_health": 50, "n_scored": fake_zero}}})
    assert fh == _NO_BASIS
    rows = [{"band": "Good", "score": 80}]
    fh = ssot.fleet_avg_health({"health_scores": rows,
                                "executive_brief": {"posture": {"avg_health": 80, "n_scored": fake_zero}}})
    assert (fh["state"], fh["value"]) == ("measured", 80)
    # the genuine integer zero still withholds, with or without rows
    fh = ssot.fleet_avg_health({"health_scores": rows,
                                "executive_brief": {"posture": {"avg_health": 80, "n_scored": 0}}})
    assert fh["state"] == "not_assessed"


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


# --------------------------------------------------------------------------------------------------
# Round 2 -- reconcile(): a finite-score overflow, and a band nobody can read
# --------------------------------------------------------------------------------------------------
_HUGE = 1.7e308                                   # finite, plain JSON; two of them overflow a float sum


def test_r2_a_float_sum_overflow_is_reconciled_not_raised():
    """Two scores of 1.7e308 (valid JSON, no Infinity token) made ``sum(scored)`` inf and ``round(inf)``
    raised OverflowError out of reconcile / summary / audit -- through docmeta, every DOCX."""
    snap = {"health_scores": [{"band": "Good", "score": _HUGE}, {"band": "Good", "score": _HUGE}],
            "executive_brief": {"posture": {"avg_health": 80}}}
    (v,) = ssot.reconcile(snap)
    assert v == f"executive_brief.posture.avg_health=80 but round(mean(scored health_scores.score))={int(_HUGE)}"
    assert ssot.summary(snap)["verified"] is False and ssot.audit(snap)["n_violations"] == 1
    # the exact mean of the huge scores IS that value: published exactly, it reconciles
    snap["executive_brief"]["posture"]["avg_health"] = int(_HUGE)
    assert ssot.reconcile(snap) == []
    # an int too big for the float sum beside a float (int + float raised before the division)
    mixed = {"health_scores": [{"band": "Good", "score": 10 ** 308}, {"band": "Good", "score": 10 ** 308},
                               {"band": "Good", "score": 1.5}],
             "executive_brief": {"posture": {"avg_health": 1}}}
    assert len(ssot.reconcile(mixed)) == 1


def test_r2_an_in_range_mean_rounds_exactly_as_the_producer_does():
    """The overflow fallback must not move a half-way rounding the producer's float mean decides."""
    for scores in ([70, 71], [0.5, 1.5, 2.5], [33.3, 33.3, 33.4], [99.5], [12, 13, 14, 15], [0.1] * 10):
        rows = [{"switch": f"s{i}", "band": "Good", "score": s} for i, s in enumerate(scores)]
        assert ssot.reconcile({"health_scores": rows, "executive_brief": {"posture": {
            "avg_health": round(sum(scores) / len(scores))}}}) == [], scores


_UNREADABLE = ([], ["Critical"], {"band": "Critical"}, "Unrecognised", 7, None, "")


@pytest.mark.parametrize("band", _UNREADABLE, ids=["empty-list", "list", "dict", "text", "int", "none", "empty"])
def test_r2_an_unreadable_band_leaves_the_band_facts_unverified(band):
    """The refuter's reproduction: bands ``[["Critical"], {"x": 1}]`` with ``n_critical: 0`` and
    ``worst_band: Critical`` gave ``verified: True, n_violations: 0``. A row whose band is outside the
    producer's vocabulary could be any band, so no published band count or worst band can be confirmed."""
    rows = [{"switch": "a", "band": band, "score": 10}, {"switch": "b", "band": "Good", "score": 80}]
    snap = {"health_scores": rows,
            "executive_brief": {"posture": {"avg_health": 45, "n_critical": 0, "n_poor": 0, "worst_band": "Good"}}}
    got = ssot.reconcile(snap)
    assert [v.split("=", 1)[0] for v in got] == ["executive_brief.posture.n_critical",
                                                 "executive_brief.posture.n_poor",
                                                 "executive_brief.posture.worst_band"], got
    assert all("1 health row(s) carry no recognised band" in v for v in got), got
    s = ssot.summary(snap)
    assert s["verified"] is False and s["n_violations"] == 3


def test_r2_the_refuters_exact_reproduction_is_no_longer_verified():
    snap = {"health_scores": [{"switch": "a", "band": ["Critical"], "score": 10},
                              {"switch": "b", "band": {"x": 1}, "score": 30}],
            "executive_brief": {"posture": {"avg_health": 20, "n_critical": 0, "worst_band": "Critical"}}}
    s = ssot.summary(snap)
    assert s["verified"] is False and s["n_violations"] == 2, s


def test_r2_a_row_that_is_not_a_record_is_unreadable_too():
    snap = {"health_scores": ["sw1", {"switch": "b", "band": "Good", "score": 80}],
            "executive_brief": {"posture": {"n_critical": 0}}}
    assert ssot.reconcile(snap) == [
        "executive_brief.posture.n_critical=0 but 1 health row(s) carry no recognised band, "
        "so count(health_scores.band==Critical) cannot be verified"]


def test_r2_a_readable_critical_row_still_decides_the_worst_band():
    """Nothing is worse than Critical, so an observed Critical row confirms worst_band=Critical even beside an
    unreadable row -- only the facts that row could change are withheld."""
    rows = [{"switch": "a", "band": 7, "score": 10}, {"switch": "b", "band": "Critical", "score": 20}]
    snap = {"health_scores": rows, "executive_brief": {"posture": {"worst_band": "Critical"}}}
    assert ssot.reconcile(snap) == []


def test_r2_every_band_the_producer_emits_is_readable():
    """The vocabulary is the producer's: every band compute_health_scores can emit plus the unscored band, and
    the real sample fleet and the golden snapshot raise no new violation."""
    from cisco_toolkit import analyze
    emitted = {label for _thr, label, _fill in analyze.SCORING.bands} | {"Insufficient Data"}
    assert emitted == set(ssot._HEALTH_BAND_ORDER) | {ssot._HEALTH_BAND_NOT_SCORED}
    for path in (SAMPLE, ROOT / "tests" / "golden" / "snapshot.json"):
        snap = json.loads(path.read_text(encoding="utf-8"))
        assert snap["health_scores"] and ssot.reconcile(snap) == [], path.name


# --------------------------------------------------------------------------------------------------
# Round 2 -- _is_deep_empty holds what it entered; str()/repr() of a hostile value is bounded
# --------------------------------------------------------------------------------------------------
class _FreshChildren(list):
    """A container whose iteration builds NEW children: each is freed once the walk moves past it, so an
    id-only memo can see a later child at a reused id and skip it."""

    def __iter__(self):
        for i in range(64):
            yield [["evidence"]] if i == 63 else [[0]]


def test_r2_deep_empty_holds_every_container_it_entered():
    assert _recursive_is_deep_empty(_FreshChildren()) is False
    for _ in range(20):                                       # allocator reuse is the trigger: repeat it
        assert ssot._is_deep_empty(_FreshChildren()) is False


_TOO_DEEP = 20000                                           # past what str()/repr() of a nesting can render


def test_r2_the_nesting_really_defeats_str():
    with pytest.raises(RecursionError):
        str(_nest(_TOO_DEEP, 0, "list"))


def test_r2_a_deep_failure_label_is_unknown_not_raised():
    label = _nest(_TOO_DEEP, "Health Scores", "list")
    assert ssot.phase_classification(label) == "unknown"
    assert ssot.failed_sections({"assessment_integrity": {"failed_phases": [label]}}) == (frozenset(), True)
    for scalar, kind in ((7, "unknown"), (None, "unknown"), ("Health Scores", "sections")):
        assert ssot.phase_classification(scalar) == kind


def test_r2_reconcile_messages_bound_a_hostile_value():
    deep = _nest(_TOO_DEEP, 0, "list")
    (v,) = ssot.reconcile({"health_scores": [], "executive_brief": {"posture": {"avg_health": deep}}})
    assert v.startswith("executive_brief.posture.avg_health=[[[") and len(v) < 300, v[:300]
    (v,) = ssot.reconcile({"health_scores": [{"switch": "a", "band": "Poor", "score": 40}],
                           "executive_brief": {"posture": {"worst_band": deep}}})
    assert v.startswith("executive_brief.posture.worst_band=[[[") and v.endswith("present='Poor'"), v[:300]
    by_band = {"health_scores": [], "lifecycle_risk": {"per_device": [{"band": "Active"}],
                                                      "summary": {"by_band": {"Active": 2}}}}
    assert ssot.reconcile(by_band) == [
        "lifecycle_risk.summary.by_band[Active]=2 but count(per_device.band==Active)=1"]   # unchanged text


def test_r2_segmentation_facts_bounds_hostile_names():
    deep = _nest(_TOO_DEEP, "vrf-x", "list")
    owner = {"segmentation": {"gateway_acl": {"n_gateways": 1}, "vrfs": [{"vrf": deep}]}}
    assert len(ssot.segmentation_facts(owner)["gateway_vrfs"]) == 1
    derived = {"interfaces": {"sw1": {"Vlan10": {"vrf": deep, "svi_ip": deep, "acl_in": deep}}}}
    facts = ssot.segmentation_facts(derived)
    assert (facts["n_gateways"], facts["n_with_acl"], facts["source"]) == (1, 1, "derived")
    # ordinary names are read exactly as before
    plain = {"interfaces": {"sw1": {"Vlan10": {"vrf": "BLUE", "svi_ip": "10.0.0.1"},
                                    "mgmt0": {"vrf": "management"}}}}
    got = ssot.segmentation_facts(plain)
    assert (got["gateway_vrfs"], got["other_vrfs"], got["n_with_acl"]) == (["BLUE"], ["management"], 0)


def test_r2_a_non_string_host_or_device_is_total():
    """``(d.get("host") or "").strip()`` raised AttributeError on a numeric host row, and a pack's
    ``"device": 7`` aborted assertions.evaluate_pack. A host row that is not a string names no device; a
    device that is not a string names no host the evidence can confirm was collected, so a fact scoped to it
    abstains (a blind spot), never a fleet-level PASS under its name."""
    from cisco_toolkit import assertions
    snap = {"collection_completeness": {"devices": [{"host": 7, "status": "not collected"},
                                                    {"host": "sw1", "status": _nest(_TOO_DEEP, 0, "list")},
                                                    {"host": "SW2", "status": "Not Collected"}]},
            "qos_audit": {"n": 3}}
    subject = "qos_audit.n"
    assert ssot.abstention_reason(snap, subject, "sw9") == PUB
    assert ssot.abstention_reason(snap, subject, "sw1") == PUB               # an unreadable status is no match
    assert ssot.abstention_reason(snap, subject, " sw2 ") == "not_collected"   # unchanged normalisation
    for device in (7, ["sw1"], {"host": "sw1"}):
        assert ssot.abstention_reason(snap, subject, device) == "not_collected", device
    for device in ("", None, 0):                                             # no device given: fleet level
        assert ssot.abstention_reason(snap, subject, device) == PUB, device
    rule = {"type": "comparison", "op": ">=", "value": 1}
    res = assertions.evaluate_pack(snap, {"assertions": [
        {"id": "a", "subject": subject, "device": "sw9", "all_of": [rule]},
        {"id": "b", "subject": subject, "device": 7, "all_of": [rule]}]})
    assert [r["status"] for r in res["results"]] == [assertions.PASS, assertions.NOT_OBSERVED]


# --------------------------------------------------------------------------------------------------
# Round 2 -- the abstention core agrees with fleet_avg_health on a snapshot with no health rows
# --------------------------------------------------------------------------------------------------
_POSTURE_PATHS = tuple(p for p, _c in ssot.CANONICAL_FACTS.values() if p.startswith("executive_brief.posture."))


def _no_rows(snap, rows=None):
    snap = json.loads(json.dumps(snap))
    if rows is None:
        snap.pop("health_scores", None)
    else:
        snap["health_scores"] = rows
    return snap


@pytest.mark.parametrize("rows", [None, {"sw1": {"score": 80}}, "rows"], ids=["absent", "dict", "text"])
def test_r2_posture_facts_without_a_health_list_are_not_collected(rows):
    """Every posture fact is an aggregate over the health rows. Without a health_scores LIST the snapshot
    carries nothing they were computed over: the abstention core said ``published`` (``collected_but_empty``
    for a stripped zero) while fleet_avg_health withholds the same number, and a user assertion
    ``n_critical == 0`` PASSED on no evidence."""
    from cisco_toolkit import assertions
    snap = _no_rows(_sample(), rows)
    assert _POSTURE_PATHS == ("executive_brief.posture.avg_health", "executive_brief.posture.n_critical",
                              "executive_brief.posture.n_poor", "executive_brief.posture.worst_band")
    for path in _POSTURE_PATHS + ("executive_brief.posture",):
        assert ssot.abstention_reason(snap, path) == "not_collected", path
    lineage = {f["path"]: f["state"] for f in ssot.compute_fact_lineage(snap)["facts"]}
    assert {lineage[p] for p in _POSTURE_PATHS} == {"not_collected"}
    zero = {"executive_brief": {"posture": {"avg_health": 0, "n_critical": 0, "n_poor": 0, "worst_band": ""}}}
    assert ssot.abstention_reason(zero, "executive_brief.posture.n_critical") == "not_collected"
    res = assertions.evaluate_assertion(zero, {"id": "c", "subject": "executive_brief.posture.n_critical",
                                               "all_of": [{"type": "comparison", "op": "==", "value": 0}]})
    assert res["status"] == assertions.NOT_OBSERVED, res
    # the facts outside the posture keep their own verdicts
    assert ssot.abstention_reason(snap, "executive_brief.scale.n_devices") == PUB


def test_r2_posture_facts_over_a_real_list_are_unchanged():
    sample = _sample()
    assert {ssot.abstention_reason(sample, p) for p in _POSTURE_PATHS} == {PUB}
    failed = _no_rows(sample, [])
    failed["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    assert {ssot.abstention_reason(failed, p) for p in _POSTURE_PATHS} == {ssot.ANALYSIS_UNAVAILABLE}
    # a failed Health Scores phase whose list is ABSENT is still the failure, not a blind spot
    failed.pop("health_scores")
    assert {ssot.abstention_reason(failed, p) for p in _POSTURE_PATHS} == {ssot.ANALYSIS_UNAVAILABLE}
    n_lineage = 0
    for path in (SAMPLE, ROOT / "tests" / "golden" / "snapshot.json"):
        snap = json.loads(path.read_text(encoding="utf-8"))
        if "fact_lineage" in snap:
            n_lineage += 1
            assert ssot.compute_fact_lineage(snap) == snap["fact_lineage"], path.name
    assert n_lineage, "neither stored snapshot carries fact_lineage: this check compared nothing"


# --------------------------------------------------------------------------------------------------
# Round 2 -- summary() never counts a figure its own owner withholds as a published headline figure
# --------------------------------------------------------------------------------------------------
def test_r2_summary_does_not_count_the_posture_facts_of_a_snapshot_with_no_health_list():
    """The DOCX page said "average health UNVERIFIED" under a badge "N headline figures self-verified" that
    counted that average and its unbacked siblings among the N."""
    sample = _sample()
    base = ssot.summary(sample)
    for rows in (None, {"sw1": {"score": 80}}):
        s = ssot.summary(_no_rows(sample, rows))
        assert s["n_facts"] == base["n_facts"] - len(_POSTURE_PATHS), (rows, s, base)


@pytest.mark.parametrize("avg", ["abc", "72", float("nan")], ids=["text", "numeric-text", "nan"])
def test_r2_summary_does_not_count_an_unverified_average(avg):
    sample = _sample()
    base = ssot.summary(sample)
    sample["executive_brief"]["posture"]["avg_health"] = avg
    assert ssot.fleet_avg_health(sample)["state"] == "unverified"
    assert ssot.summary(sample)["n_facts"] == base["n_facts"] - 1


def test_r2_summary_of_engine_output_is_unchanged():
    """The engine stamps summary() into executive_brief.ssot; its own output keeps every count."""
    sample = _sample()
    assert ssot.summary(sample) == sample["executive_brief"]["ssot"]
    assert ssot.fleet_avg_health(sample)["state"] == "measured"


@pytest.mark.parametrize("snap", [None, [], "snapshot", 7], ids=["none", "list", "text", "int"])
def test_r2_the_reconciliation_entry_points_are_total_on_a_non_dict(snap):
    assert ssot.reconcile(snap) == []
    assert ssot.audit(snap) is None
    assert ssot.summary(snap) == {"verified": False, "n_facts": 0, "n_checked": 0, "n_violations": 0}


# --------------------------------------------------------------------------------------------------
# Round 2 -- the explorer's port of the reader (a known divergence, pinned so it cannot be forgotten)
# --------------------------------------------------------------------------------------------------
NODE = shutil.which("node")
EXPLORER = ROOT / "cisco_toolkit" / "blast_radius_explorer.html"
_AGREEING = (
    {"health_scores": [{"band": "Good", "score": 80}], "executive_brief": {"posture": {"avg_health": 80}}},
    {"health_scores": [{"band": "Insufficient Data", "score": 100}],
     "executive_brief": {"posture": {"avg_health": None, "n_scored": 0}}},
    {"health_scores": [{"band": "Insufficient Data", "score": 100}], "executive_brief": {"posture": {"avg_health": 0}}},
    {"health_scores": [{"band": "Good", "score": 80}], "executive_brief": {"posture": {"avg_health": "abc"}}},
    {"executive_brief": {"posture": {"avg_health": None, "n_scored": 0}}},
    {"health_scores": [{"band": "Good", "score": 80}]},
    {"health_scores": [{"band": "Good", "score": 80}], "executive_brief": {"_unavailable": True}},
)
_DIVERGENT = (                                            # Python: unverified / no_scored_basis
    {"executive_brief": {"posture": {"avg_health": 72}}},
    {"executive_brief": {"posture": {"avg_health": 0, "n_critical": 0, "n_poor": 0, "worst_band": ""}}},
    {"health_scores": {"sw1": {"score": 80}}, "executive_brief": {"posture": {"avg_health": 50}}},
    {"executive_brief": {"posture": {"avg_health": 50, "n_scored": 1}}},
)


def _explorer_states(cases, tmp_path):
    block = re.search(r"/\* FLEET-AVG-HEALTH START \*/(.*?)/\* FLEET-AVG-HEALTH END \*/",
                      EXPLORER.read_text(encoding="utf-8"), re.S)
    if not block:     # not an AssertionError: the strict xfail below must never swallow a broken harness
        raise RuntimeError("the explorer's fleet-average reader (FLEET-AVG-HEALTH block) is missing")
    driver = tmp_path / "parity.js"
    driver.write_text(
        "let SNAP=null;\n"
        "function healthList(){return SNAP&&SNAP.health_scores?SNAP.health_scores:[];}\n"   # the explorer's
        + block.group(1) + "\n"
        + "const cases=" + json.dumps(list(cases)) + ";\n"
        + "process.stdout.write(JSON.stringify(cases.map(c=>{SNAP=c;return fleetHealthState(healthList()).state;})));\n",
        encoding="utf-8")
    proc = subprocess.run([NODE, str(driver)], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"explorer parity driver failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


@pytest.mark.skipif(not NODE, reason="node is not installed -- executed explorer check skipped")
def test_r2_explorer_reader_agrees_with_the_owner_where_both_have_the_rule(tmp_path):
    assert _explorer_states(_AGREEING, tmp_path) == [ssot.fleet_avg_health(c)["state"] for c in _AGREEING]


@pytest.mark.skipif(not NODE, reason="node is not installed -- executed explorer check skipped")
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="the explorer's fleetHealthState port lacks the no_scored_basis rule "
                          "(docs/ssot-contract.md); port it, then delete this marker")
def test_r2_explorer_reader_agrees_on_a_number_with_no_scored_row_basis(tmp_path):
    want = [ssot.fleet_avg_health(c)["state"] for c in _DIVERGENT]
    assert _explorer_states(_DIVERGENT, tmp_path) == want


def test_r2_the_owner_withholds_every_divergent_case():
    """The Python half of the pinned divergence, outside the xfail so a regression here cannot hide in it."""
    assert [ssot.fleet_avg_health(c)["reason"] for c in _DIVERGENT] == ["no_scored_basis"] * len(_DIVERGENT)
