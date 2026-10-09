"""W50: the versioned operator-evidence receipt contract (``cutover_operator_evidence``).

AssessHub persists every execution comparison, its ``operator_evidence`` included, inside an execution comparison
receipt and re-verifies each stored receipt against an exact-source recomputation on every read
(``webapp/backend/storage.py``). So whatever a contract binds must never change for the same snapshot bytes, or every
stored receipt of that contract reads as mismatched (409) and its execution history becomes unreadable. Pinned here:

1. **/1 is frozen.** Receipts stored before W50 declare ``cutover_operator_evidence/1``. Its recomputation must
   reproduce, byte for byte, the digests the pre-W50 engine produced: measured at ``e7c00e12`` (the W48 head W50 was
   cut from) on the committed golden and sample, with the canonical encoding below. These are constants, never
   recomputed from current code, so the legacy path cannot drift together with its own test.
2. **/2 is pinned the same way.** It binds only the engine owner's stable semantics: the verdict token, the reason
   CODES (with the count each quotes) and each measure's stored value or an explicit withheld marker. It binds no
   prose (``why``, ``table_detail``, ``CODE_PHRASES``) and no rendering rule (``≥ N``, ``(lower bound)``), and a test
   rewords every owner phrase to prove the pinned bytes do not move.
3. **The owner declares the version of those semantics** (``impact_assessability.SCHEMA``, bound in /2's
   ``impacts_owner``). Changing what the owner decides without bumping it fails here.
4. **The dispatch is explicit** and the frozen legacy function has exactly one call site.

The rule when a pin moves (stated once, here):

* If a **/2** digest changes, /2 changed. Do NOT re-pin: add ``cutover_operator_evidence/3`` as the new current
  contract, freeze today's /2 computation as a named legacy function (``_rehearsal_impacts_v2_legacy``), select it
  for /2 in the dispatch exactly as ``_rehearsal_impacts_v1_legacy`` is selected for /1, and pin /3 here. A stored
  /2 receipt must keep verifying.
* If only a **comparison** digest changes while its operator-evidence digest holds, the change is outside this
  contract (another comparison owner) and it breaks every stored receipt of every contract alike: that needs its own
  receipt-versioning decision, not a re-pin.
* Until W50 reaches ``main`` no /2 receipt can exist anywhere, so a supervisor may re-pin /2 once, deliberately, in
  the merge that changes it (for example W48's fix round), and must say so in the handoff log.

Digests use ``protocol_assurance.canonical_json_bytes`` (sorted keys, ASCII, compact) over
``cutover_operator_evidence(snap, prior_snapshot=snap)`` and over ``compare_bound_pair(snap, snap, ...)`` with the
fixed persisted-source bindings of :func:`_binding`, ``snap`` being ``bind_snapshot_json_bytes`` of the file bytes.

No test here runs a pipeline. Written for the hosted runners (owner GitHub-only rule); not run locally.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import pathlib

import pytest

from cisco_toolkit import impact_assessability as ia
from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.comparison import compare_bound_pair

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
_CORPUS = {"golden": GOLDEN, "sample": SAMPLE}
V1 = pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1
V2 = pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V2
WITHHELD = dict(pa.IMPACT_CELL_WITHHELD)

# ---------------------------------------------------------------------------------------------------------------
# the frozen and pinned digests
# ---------------------------------------------------------------------------------------------------------------
#: cutover_operator_evidence/1 as the pre-W50 engine computed it, measured at e7c00e12 (frozen; never re-pin).
_V1_FROZEN = {
    "golden": {
        "operator_evidence": "9da4d736cb8c1bfbe6ed4fe69c4ea01bacfd40ed2a353b50fa7368e8d3f75557",
        "comparison": "56b1c51c69a0fe79c0ad193d78479aecee228c3acc4d7a1c8eab28a506cd0ce2",
    },
    "sample": {
        "operator_evidence": "ab1f6d468e57cba53658dff2af81baa25498fcf674f805d3a783dcd83c7c7b32",
        "comparison": "0c81ec1949fe4af0344dd5953f6a7306832e1c4497a757a9ee92563870d53744",
    },
}

#: cutover_operator_evidence/2. If one changes, add /3 and freeze /2 (module docstring); never re-pin a /2 that a
#: stored receipt may carry.
_V2_PINNED = {
    "golden": {
        "operator_evidence": "e9aedbb835090df570132111f698e388343d48739fe4375b07dc501d5c97c713",
        "comparison": "30ed44b2ac4fbda336e9739e3ccecef7900022a96749e2bb85b53b85b9e56e83",
    },
    "sample": {
        "operator_evidence": "cb916b4ead4448cb53c59bb64e91c1a21a834642954ac62b9abf0c512b818aea",
        "comparison": "a1d9a5040ac4789f5a71b9e673f66103c367ba3936bdb3c2a488aea417694d1f",
    },
}

#: The owner's bound semantics per declared owner version (``ia.SCHEMA``): over the golden, the sample and a battery
#: of golden variants that exercises every reason code. A change here under an unchanged ``ia.SCHEMA`` fails.
_OWNER_SEMANTICS = {
    "failure_impact_assessability/1": {
        "golden": "7f06243ce235412e0ae0dcb1d3577f196496fd1eda5139f5c12a5ad4dfd8f9de",
        "sample": "329e7bfbc4f7c54c97e90a355d0ac9cb1e91113436e9752e38b1819ea6ea228b",
        "battery": "a98056a2099f4a6465feb0a1c6b0d2548d55bad9f725b2553c95e3c46d24e83d",
    },
}


def _sha(value) -> str:
    return hashlib.sha256(pa.canonical_json_bytes(value)).hexdigest()


def _bound(name):
    raw = _CORPUS[name].read_bytes()
    return raw, pa.bind_snapshot_json_bytes(raw)


def _binding(raw: bytes, snapshot_id: int) -> dict:
    """The fixed persisted-source binding the pins were measured with (both sides bind the same bytes)."""
    return {
        "snapshot_id": snapshot_id,
        "campaign_id": 1,
        "engagement_id": "E",
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "source": pa.PERSISTED_SOURCE,
        "label": "x",
    }


def _digests(name: str, contract: str) -> dict:
    """The operator-evidence and full-comparison digests of one corpus snapshot under one declared contract."""
    raw, snap = _bound(name)
    evidence = pa.cutover_operator_evidence(snap, prior_snapshot=snap, schema=contract)
    assert evidence["schema"] == contract
    comparison = compare_bound_pair(
        snap, snap, before_binding=_binding(raw, 1), after_binding=_binding(raw, 2),
        operator_evidence_schema=contract,
    )
    assert comparison["operator_evidence"] == evidence
    return {"operator_evidence": _sha(evidence), "comparison": _sha(dict(comparison))}


def _require_corpus():
    missing = [str(path) for path in _CORPUS.values() if not path.exists()]
    if missing:
        pytest.skip(f"corpus snapshot not present: {missing}")


@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_v1_recomputes_the_frozen_pre_w50_bytes(name):
    """/1 receipts stored before W50 keep verifying only while /1 recomputes exactly what the pre-W50 engine wrote."""
    _require_corpus()
    assert _digests(name, V1) == _V1_FROZEN[name], (
        "cutover_operator_evidence/1 no longer recomputes the bytes the pre-W50 engine stored, so every stored /1 "
        "receipt would fail re-verification. Restore _rehearsal_impacts_v1_legacy and the shared payload; if only "
        "'comparison' moved, a change outside this contract breaks every stored receipt (module docstring).")


@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_v2_recomputes_its_pinned_bytes(name):
    """The rule when this fails: add cutover_operator_evidence/3 and freeze /2's computation as a named legacy
    function, exactly as /1 is frozen (module docstring). Never re-pin a /2 that a stored receipt may carry."""
    _require_corpus()
    assert _digests(name, V2) == _V2_PINNED[name], (
        "cutover_operator_evidence/2 changed: a stored /2 receipt would no longer verify. Add /3 as the current "
        "contract and freeze today's /2 as _rehearsal_impacts_v2_legacy (see this module's docstring).")


def test_the_current_contract_is_v2_and_its_default_is_the_pinned_one():
    _require_corpus()
    assert pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA == V2
    raw, snap = _bound("golden")
    assert _sha(pa.cutover_operator_evidence(snap, prior_snapshot=snap)) == _V2_PINNED["golden"]["operator_evidence"]


def _reword_every_owner_phrase(monkeypatch):
    """Reword every reader-facing string the owner renders: every phrase, verdict label, cell word, state word and
    reason template (format fields kept, so the owner still renders)."""
    monkeypatch.setattr(ia, "CODE_PHRASES", type(ia.CODE_PHRASES)(
        {code: "REWORDED " + phrase for code, phrase in ia.CODE_PHRASES.items()}))
    monkeypatch.setattr(ia, "VERDICT_LABELS", type(ia.VERDICT_LABELS)(
        {verdict: "REWORDED " + label for verdict, label in ia.VERDICT_LABELS.items()}))
    monkeypatch.setattr(ia, "STATE_WORD", type(ia.STATE_WORD)(
        {state: "REWORDED " + word for state, word in ia.STATE_WORD.items()}))
    monkeypatch.setattr(ia, "NOT_ASSESSED_CELL", "REWORDED not assessed")
    monkeypatch.setattr(ia, "LOWER_BOUND_MARK", "(REWORDED lower bound)")
    for name in dir(ia):
        if name.startswith("R_") and isinstance(getattr(ia, name), str):
            monkeypatch.setattr(ia, name, "REWORDED " + getattr(ia, name))


@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_rewording_the_owner_never_moves_a_stored_v2_receipt(name, monkeypatch):
    """The P2 this contract exists for: a later owner wording change (W48's fix round is the next one) must leave
    every stored /2 receipt verifiable. Reword everything the owner says; the /2 bytes do not move."""
    _require_corpus()
    raw, snap = _bound(name)
    before = pa.cutover_operator_evidence(snap, prior_snapshot=snap)
    _reword_every_owner_phrase(monkeypatch)
    rows = ia.rows_with_verdicts(snap)
    if any(not verdict.published for _row, verdict in rows):       # non-vacuity: the rewording reached the owner
        assert any("REWORDED" in verdict.why for _row, verdict in rows if not verdict.published)
    after = pa.cutover_operator_evidence(snap, prior_snapshot=snap)
    assert after == before
    assert b"REWORDED" not in pa.canonical_json_bytes(after)
    assert _digests(name, V2) == _V2_PINNED[name]


# ---------------------------------------------------------------------------------------------------------------
# the owner's declared semantic version
# ---------------------------------------------------------------------------------------------------------------
def owner_semantics(snap) -> list:
    """What the owner DECIDES per stored row, prose excluded: the verdict, each reason code with its count, which
    cells it withholds and how a ranking may place the row. /2 binds exactly these decisions."""
    return [{
        "index": verdict.index,
        "host": verdict.host,
        "assessable": verdict.assessable,
        "code_counts": [[code, n] for code, n in verdict.code_counts],
        "withheld": [field for field in ia.IMPACT_FIELDS if verdict.withholds(field)],
        "ranks": ia.ranks(verdict),
        "ranking_floor": ia.ranking_floor(verdict),
    } for verdict in ia.assess_failure_impact(snap)]


def owner_battery() -> dict:
    """Golden variants, one per reason code the golden itself does not carry (core2 already faces an uncollected
    neighbour). Each is the smallest stored-evidence change that should trigger that code."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def core1(snap):
        return next(row for row in snap["failure_impact"] if isinstance(row, dict) and row.get("host") == "core1")

    def variant(mutate):
        snap = copy.deepcopy(golden)
        mutate(snap)
        return snap

    def set_core1(**values):
        return lambda snap: core1(snap).update(values)

    def drop_core1(key):
        return lambda snap: core1(snap).pop(key)

    def no_run_config(snap):
        for port in snap["interfaces"]["core1"].values():
            if isinstance(port, dict):
                port["run_config_observed"] = False

    return {
        "section_unavailable": variant(
            lambda snap: snap.__setitem__("assessment_integrity", {"failed_phases": ["Failure Impact"]})),
        "row_unreadable": variant(lambda snap: snap["failure_impact"].append("not an object")),
        "duplicate_host": variant(lambda snap: snap["failure_impact"].append(copy.deepcopy(core1(snap)))),
        "indeterminate": variant(set_core1(detail=ia.IMPACT_INDETERMINATE_PREFIX + ": no VLAN evidence")),
        "legacy_row": variant(drop_core1("off_scan_gw_vlans")),
        "off_scan_unreadable": variant(set_core1(off_scan_gw_vlans="two")),
        "blind_links_unreadable": variant(set_core1(blind_links="two")),
        "no_host": variant(set_core1(host=7)),
        "no_run_config": variant(no_run_config),
        "off_scan_only": variant(set_core1(off_scan_gw_vlans=2, vlans_impacted=0)),
        "blind_links_only": variant(set_core1(blind_links=2, vlans_impacted=0)),
        "off_scan_partial": variant(set_core1(off_scan_gw_vlans=1)),
        "blind_links": variant(set_core1(blind_links=1)),
        "blind_links_legacy": variant(drop_core1("blind_links")),
        "neighbours_unreadable": variant(lambda snap: snap["cable_map"].__setitem__("cables", "unreadable")),
    }


def owner_semantics_digests() -> dict:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    battery = {name: owner_semantics(snap) for name, snap in owner_battery().items()}
    return {"golden": _sha(owner_semantics(golden)), "sample": _sha(owner_semantics(sample)), "battery": _sha(battery)}


def test_the_battery_exercises_every_reason_code_the_owner_declares():
    """The semantic pin covers the owner's closed code set (the keys of CODE_PHRASES): each battery variant triggers
    the code it is named for, and golden + battery together exercise every code. A new code fails here until a
    variant exercises it, and its digest moves, which needs an ia.SCHEMA bump."""
    _require_corpus()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    seen = {code for verdict in ia.assess_failure_impact(golden) for code in verdict.codes}
    for name, snap in owner_battery().items():
        codes = {code for verdict in ia.assess_failure_impact(snap) for code in verdict.codes}
        assert name in codes, (name, sorted(codes))
        seen |= codes
    assert seen == set(ia.CODE_PHRASES), sorted(set(ia.CODE_PHRASES) ^ seen)


def test_the_owner_bound_semantics_change_only_with_a_schema_bump():
    """``impact_assessability.SCHEMA`` is the owner's declared output version, and /2 binds it as ``impacts_owner``.
    Changing what the owner decides (a verdict, a code, its count, a withheld cell, a ranking) without bumping it
    fails here. Bumping it moves every /2 digest (impacts_owner is bound), so it also requires /3."""
    _require_corpus()
    assert ia.SCHEMA in _OWNER_SEMANTICS, (
        f"impact_assessability.SCHEMA is now {ia.SCHEMA!r}: pin its semantics here, and add "
        "cutover_operator_evidence/3 (this module's docstring), since /2 binds the previous version")
    assert owner_semantics_digests() == _OWNER_SEMANTICS[ia.SCHEMA], (
        "the owner's bound semantics changed without bumping impact_assessability.SCHEMA: bump it, pin the new "
        "semantics under the new version, and add cutover_operator_evidence/3 (stored /2 receipts bind the old)")


def test_the_semantic_pin_moves_when_the_owner_decides_differently(monkeypatch):
    """Non-vacuity: dropping every hold is a semantic change the pin must see; rewording every phrase is not."""
    _require_corpus()
    pinned = _OWNER_SEMANTICS[ia.SCHEMA]
    _reword_every_owner_phrase(monkeypatch)
    assert owner_semantics_digests() == pinned
    monkeypatch.setattr(ia, "row_hold", lambda *args, **kwargs: None)
    assert owner_semantics_digests()["battery"] != pinned["battery"]


def test_v2_binds_the_owner_version_and_census():
    _require_corpus()
    raw, snap = _bound("sample")
    rehearsal = pa.cutover_operator_evidence(snap)["rehearsal"]
    verdicts = [verdict for _row, verdict in ia.rows_with_verdicts(snap)]
    assert rehearsal["impacts_owner"] == ia.SCHEMA
    assert rehearsal["n_impacts_total"] == len(rehearsal["impacts"]) == len(verdicts)
    assert rehearsal["n_impacts_by_assessable"] == {
        k: sum(1 for verdict in verdicts if verdict.assessable == k) for k in ia.VERDICTS}


# ---------------------------------------------------------------------------------------------------------------
# what a /2 row binds, on the committed sample (core1: one inter-switch link with no trunk/STP evidence)
# ---------------------------------------------------------------------------------------------------------------
_ROW_KEYS = {"index", "host", "assessable", "reason_codes", "detail", *ia.IMPACT_MEASURES}


@pytest.fixture(scope="module")
def sample():
    if not SAMPLE.exists():
        pytest.skip("sample_fleet.snapshot.json not present")
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _core1(snap):
    pairs = [(row, verdict) for row, verdict in ia.rows_with_verdicts(snap) if row.get("host") == "core1"]
    assert len(pairs) == 1, pairs
    return pairs[0]


def _v2_core1(snap):
    evidence = pa.cutover_operator_evidence(snap)
    assert evidence["schema"] == V2
    rows = [row for row in evidence["rehearsal"]["impacts"] if row.get("host") == "core1"]
    assert len(rows) == 1, rows
    return evidence, rows[0]


def _expected_cell(verdict, field):
    return WITHHELD if verdict.withholds(field) else verdict.raw.get(field)


def _no_owner_prose(evidence, verdicts):
    """No reader-facing owner string reaches the bound rows (the rest of the payload has its own owners)."""
    text = pa.canonical_json_bytes(evidence["rehearsal"]["impacts"]).decode("ascii")
    for verdict in verdicts:
        if verdict.published:
            continue
        for phrase in [verdict.why, verdict.summary, ia.table_detail(verdict), *verdict.reasons]:
            assert json.dumps(phrase)[1:-1] not in text, phrase
    for word in (ia.NOT_ASSESSED_CELL, ia.LOWER_BOUND_MARK, "\\u2265"):
        assert word not in text, word


def test_v2_binds_core1_as_a_lower_bound_by_code_and_stored_values(sample):
    row, verdict = _core1(sample)
    assert verdict.assessable == ia.LOWER_BOUND and verdict.codes == ["blind_links"], verdict.as_dict()
    evidence, item = _v2_core1(sample)
    assert set(item) == _ROW_KEYS, sorted(item)
    assert item["index"] == verdict.index and item["host"] == "core1"
    assert item["assessable"] == ia.LOWER_BOUND
    assert item["reason_codes"] == [{"code": code, "n": n} for code, n in verdict.code_counts]
    assert item["reason_codes"] == [{"code": "blind_links", "n": row["blind_links"]}]
    for field in (*ia.IMPACT_MEASURES, "detail"):
        assert item[field] == _expected_cell(verdict, field), field
    # the floor is the stored 45, marked a floor by the verdict; the bounded zeros are withheld, never a measured 0
    assert item["stranded"] == row["stranded"] == ia.ranking_floor(verdict) > 0
    assert item["severity"] == row["severity"] == ia.IMPACT_WORST
    assert item["backup"] == item["fhrp"] == WITHHELD
    _no_owner_prose(evidence, [v for _r, v in ia.rows_with_verdicts(sample)])


def test_v2_binds_a_held_core1_as_not_assessed_with_every_cell_withheld(sample):
    snap = copy.deepcopy(sample)
    del next(r for r in snap["failure_impact"] if isinstance(r, dict) and r.get("host") == "core1")[
        "off_scan_gw_vlans"]
    _row, verdict = _core1(snap)
    evidence, item = _v2_core1(snap)
    assert item["assessable"] == ia.NOT_ASSESSED == verdict.assessable
    assert item["reason_codes"] == [{"code": "legacy_row", "n": 0}]
    assert all(item[field] == WITHHELD for field in (*ia.IMPACT_MEASURES, "detail")), item
    _no_owner_prose(evidence, [v for _r, v in ia.rows_with_verdicts(snap)])


def test_v2_ranks_rows_by_the_owner_floor_then_discloses_the_rest(sample):
    """A capped view shows the largest stranded floors first (P3: never producer order): the rows the owner ranks,
    by floor or measured count with stored order breaking ties, then every row it does not rank, in stored order."""
    impacts = pa.cutover_operator_evidence(sample)["rehearsal"]["impacts"]
    verdicts = {verdict.index: (row, verdict) for row, verdict in ia.rows_with_verdicts(sample)}
    assert sorted(item["index"] for item in impacts) == sorted(verdicts)

    def key(index):
        row, verdict = verdicts[index]
        floor = ia.ranking_floor(verdict)
        return -(floor if floor is not None else row["stranded"]), index

    ranked = sorted((i for i, (_r, v) in verdicts.items() if ia.ranks(v)), key=key)
    unranked = sorted(i for i, (_r, v) in verdicts.items() if not ia.ranks(v))
    assert [item["index"] for item in impacts] == ranked + unranked
    assert impacts[0]["host"] == "core1" and impacts[0]["assessable"] == ia.LOWER_BOUND   # the 45 floor leads
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    order = [(item["host"], item["assessable"]) for item in pa.cutover_operator_evidence(golden)["rehearsal"]["impacts"]]
    assert order == [("core1", ia.PUBLISHED), ("access1", ia.PUBLISHED), ("core2", ia.LOWER_BOUND)], order


# ---------------------------------------------------------------------------------------------------------------
# /1, the dispatch and the legacy function's single call site
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("held", [False, True])
def test_the_legacy_v1_recomputation_is_the_verbatim_raw_row_copy_and_only_on_request(held, sample):
    """/1 adds nothing to /2's shared payload and copies every stored object row raw; it is reachable only by naming
    /1 explicitly, the default is /2, and an unknown or mistyped contract raises instead of being computed."""
    snap = copy.deepcopy(sample)
    if held:
        del next(r for r in snap["failure_impact"] if isinstance(r, dict) and r.get("host") == "core1")[
            "off_scan_gw_vlans"]
    legacy = pa.cutover_operator_evidence(snap, schema=V1)
    assert legacy["schema"] == V1
    rehearsal = legacy["rehearsal"]
    assert rehearsal["impacts"] == [dict(r) for r in snap["failure_impact"] if isinstance(r, dict)]
    assert set(rehearsal) == {"status", "assurance_level", "source_owner", "n_impacts_total", "impacts",
                              "l2_failure_rehearsal", "note"}, sorted(rehearsal)
    current = pa.cutover_operator_evidence(snap)
    assert current["schema"] == V2
    for key in ("owner", "owns_verdict", "current_baseline_blocker_export", "rollback"):
        assert legacy[key] == current[key], key
    for key in ("status", "assurance_level", "source_owner", "n_impacts_total", "l2_failure_rehearsal", "note"):
        assert rehearsal[key] == current["rehearsal"][key], key
    for unknown in ("cutover_operator_evidence/3", "cutover_operator_evidence/0", "", 2, ["cutover_operator_evidence/2"],
                    "__class__", "get"):
        with pytest.raises(ValueError, match="unsupported operator-evidence contract"):
            pa.cutover_operator_evidence(snap, schema=unknown)


def test_the_dispatch_is_exactly_the_recomputable_contracts():
    assert tuple(pa._REHEARSAL_IMPACTS_BY_CONTRACT) == pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMAS == (V1, V2)
    with pytest.raises(TypeError):
        pa._REHEARSAL_IMPACTS_BY_CONTRACT["cutover_operator_evidence/3"] = pa._rehearsal_impacts_v2


def test_a_stored_comparison_names_its_contract_or_reads_as_unverified():
    assert pa.stored_operator_evidence_schema({"operator_evidence": {"schema": V1}}) == V1
    assert pa.stored_operator_evidence_schema({"operator_evidence": {"schema": V2}}) == V2
    for stored in (None, [], {}, {"operator_evidence": None}, {"operator_evidence": {}},
                   {"operator_evidence": {"schema": None}}, {"operator_evidence": {"schema": "cutover_operator_evidence/3"}},
                   {"operator_evidence": {"schema": "cutover_operator_evidence"}}, {"operator_evidence": {"schema": 1}},
                   {"operator_evidence": [{"schema": V2}]}):
        assert pa.stored_operator_evidence_schema(stored) is None, stored


_LEGACY = "_rehearsal_impacts_v1_legacy"
_DISPATCH = "_REHEARSAL_IMPACTS_BY_CONTRACT"
_PRODUCTION_ROOTS = ("cisco_toolkit", os.path.join("webapp", "backend"), "portable")


def _production_modules():
    for base in _PRODUCTION_ROOTS:
        for dirpath, dirnames, filenames in os.walk(ROOT / base):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if name.endswith(".py"):
                    path = pathlib.Path(dirpath) / name
                    yield path.relative_to(ROOT).as_posix(), path
    pipeline = ROOT / "COLLECT_PARSE_V3_23_0.py"
    if pipeline.exists():
        yield pipeline.name, pipeline


def test_the_frozen_v1_function_has_exactly_one_call_site_the_v1_dispatch_entry():
    """``_rehearsal_impacts_v1_legacy`` must stay reachable only through the /1 dispatch entry, so no new comparison
    can compute raw rows. Every reference in production code is counted, not only calls: an alias would be a second
    route."""
    references, calls = [], []
    dispatch_v1 = None
    for rel, path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == _LEGACY:
                references.append((rel, node.lineno))
            elif isinstance(node, ast.Attribute) and node.attr == _LEGACY:
                references.append((rel, node.lineno))
            elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(a.name == _LEGACY for a in node.names):
                references.append((rel, node.lineno))
            if (isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
                    and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) == _LEGACY):
                calls.append((rel, node.lineno, node))
        if rel == "cisco_toolkit/protocol_assurance.py":
            for stmt in tree.body:
                target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
                    stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
                if isinstance(target, ast.Name) and target.id == _DISPATCH:
                    table = next(n for n in ast.walk(stmt.value) if isinstance(n, ast.Dict))
                    for key, value in zip(table.keys, table.values):
                        if isinstance(key, ast.Name) and key.id == "CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1":
                            dispatch_v1 = value
    assert len(calls) == 1, [(rel, line) for rel, line, _n in calls]
    assert len(references) == 1, references
    assert dispatch_v1 is not None, "the /1 entry of _REHEARSAL_IMPACTS_BY_CONTRACT is missing"
    (_rel, _line, call), = calls
    assert any(node is call for node in ast.walk(dispatch_v1)), "the one call is not the /1 dispatch entry"
