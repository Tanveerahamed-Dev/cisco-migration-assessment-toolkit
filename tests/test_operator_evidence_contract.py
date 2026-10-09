"""W50: execution receipts bind failure-impact EVIDENCE; its interpretation is display-only and computed live.

AssessHub persists every execution comparison, its ``operator_evidence`` included, inside an execution comparison
receipt and re-verifies each stored receipt by RECOMPUTING it from the bound snapshots on every read
(``webapp/backend/storage.py``). Anything a receipt binds that is derived from live, evolving code therefore makes
every stored receipt unreadable (409) the day that code changes. So:

1. **The receipt binds evidence only.** ``cutover_operator_evidence/1`` copies the after snapshot's stored
   ``failure_impact`` rows raw into ``rehearsal.impacts`` through one frozen binder
   (``protocol_assurance._rehearsal_impact_evidence_v1``) that never consults the engine owner of row assessability
   (``impact_assessability``). Its bytes are frozen at the pre-W50 values measured at ``e7c00e12`` on the committed
   golden and sample: every receipt stored before W50 still verifies, with no migration and no new version. And the
   whole comparison is independent of the owner: sabotaging every owner entry point moves no digest.
2. **The dispatch is explicit and fails closed.** ``/1`` is the dispatch's only entry; an unknown, missing or
   non-string contract raises on compute and reads as unverified on a stored receipt.
3. **The interpretation is display-only.** The owner's reading of those rows (``webapp.backend.engine
   .rehearsal_impacts_view``, the API's ``impacts_view``) is computed at request time from the bound snapshot and
   travels BESIDE a comparison, never inside it. No module on the receipt or digest path names it, and putting it
   inside a comparison would fail the detached envelope (shown below), which is why it never goes there.

Digests use ``protocol_assurance.canonical_json_bytes`` (sorted keys, ASCII, compact) over
``cutover_operator_evidence(snap, prior_snapshot=snap)`` and over ``compare_bound_pair(snap, snap, ...)`` with the fixed
persisted-source bindings of :func:`_binding`, ``snap`` being ``bind_snapshot_json_bytes`` of the file bytes.

If a frozen digest moves: never re-pin it. A change to the operator-evidence payload needs a new contract
(``cutover_operator_evidence/2``) with its own frozen binder added BESIDE /1 in the dispatch, so stored /1 receipts keep
verifying. If only the comparison digest moves, the change is outside this contract and breaks every stored receipt
alike: it needs its own receipt-versioning decision.

No test here runs a pipeline. Written for the hosted runners (owner GitHub-only rule); not run locally.
"""
from __future__ import annotations

import ast
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


def _comparison(name: str, contract=None):
    raw, snap = _bound(name)
    kwargs = {} if contract is None else {"operator_evidence_schema": contract}
    return compare_bound_pair(snap, snap, before_binding=_binding(raw, 1), after_binding=_binding(raw, 2), **kwargs)


def _digests(name: str, contract=None) -> dict:
    """The operator-evidence and full-comparison digests of one corpus snapshot (``contract`` None: the default)."""
    raw, snap = _bound(name)
    kwargs = {} if contract is None else {"schema": contract}
    evidence = pa.cutover_operator_evidence(snap, prior_snapshot=snap, **kwargs)
    assert evidence["schema"] == V1
    comparison = _comparison(name, contract)
    assert comparison["operator_evidence"] == evidence
    return {"operator_evidence": _sha(evidence), "comparison": _sha(dict(comparison))}


def _require_corpus():
    missing = [str(path) for path in _CORPUS.values() if not path.exists()]
    if missing:
        pytest.skip(f"corpus snapshot not present: {missing}")


# ---------------------------------------------------------------------------------------------------------------
# 1. the receipt binds frozen evidence, independent of the owner
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("contract", [None, V1])
@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_v1_recomputes_the_frozen_pre_w50_bytes(name, contract):
    """Every receipt stored before W50 keeps verifying only while /1 recomputes exactly what the pre-W50 engine wrote,
    both as the default a new comparison carries and as the contract a stored receipt declares."""
    _require_corpus()
    assert _digests(name, contract) == _V1_FROZEN[name], (
        "cutover_operator_evidence/1 no longer recomputes the bytes the pre-W50 engine stored, so every stored "
        "receipt would fail re-verification. Restore _rehearsal_impact_evidence_v1 and the shared payload; if only "
        "'comparison' moved, a change outside this contract breaks every stored receipt (module docstring).")


def _sabotage_the_owner(monkeypatch):
    """Make every engine-owner entry point raise and change one of its decisions (the reviewers' counterexample:
    'endpoint' leaves IMPACT_EDGE_KINDS, which moves verdicts on a real fleet)."""
    def touched(*_args, **_kwargs):
        raise AssertionError("the receipt path consulted the engine owner of row assessability")

    monkeypatch.setattr(ia, "IMPACT_EDGE_KINDS", frozenset({"ap", "phone"}))
    for name in ("assess_failure_impact", "rows_with_verdicts", "assessment_document", "row_hold", "off_scan_bound",
                 "blind_bound", "neighbour_bound", "duplicate_doubt", "table_value", "table_detail", "ranked_value",
                 "ranks", "ranking_floor", "disclose", "section_state", "count_value"):
        monkeypatch.setattr(ia, name, touched)
    monkeypatch.setattr(ia, "CODE_PHRASES", type(ia.CODE_PHRASES)(
        {code: "REWORDED " + phrase for code, phrase in ia.CODE_PHRASES.items()}))


@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_no_owner_change_can_move_a_stored_receipt(name, monkeypatch):
    """The failure that drove the pivot: an owner-valued receipt tracks every owner change, so the next change to what
    the owner decides (or how it words it) would make stored receipts unreadable. The receipt now binds evidence only,
    so with every owner entry point sabotaged the whole comparison recomputes the same frozen bytes."""
    _require_corpus()
    _sabotage_the_owner(monkeypatch)
    assert _digests(name) == _V1_FROZEN[name]


@pytest.mark.parametrize("held", [False, True])
def test_the_evidence_binder_copies_the_stored_rows_raw(held):
    """``rehearsal.impacts`` is the stored rows, raw: every object row in stored order and nothing else, so a lower
    bound's count is the producer's number and a held zero is a zero. That is evidence, never a presentation."""
    _require_corpus()
    _raw, snap = _bound("sample")
    if held:
        del next(r for r in snap["failure_impact"] if isinstance(r, dict) and r.get("host") == "core1")[
            "off_scan_gw_vlans"]
    snap["failure_impact"].append("not an object")
    rehearsal = pa.cutover_operator_evidence(snap)["rehearsal"]
    assert rehearsal["impacts"] == [dict(r) for r in snap["failure_impact"] if isinstance(r, dict)]
    assert rehearsal["n_impacts_total"] == len(rehearsal["impacts"])
    assert set(rehearsal) == {"status", "assurance_level", "source_owner", "n_impacts_total", "impacts",
                              "l2_failure_rehearsal", "note"}, sorted(rehearsal)


# ---------------------------------------------------------------------------------------------------------------
# 2. the explicit dispatch and the fail-closed declaration
# ---------------------------------------------------------------------------------------------------------------
def test_the_current_contract_is_v1_and_the_dispatch_has_only_v1():
    assert pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA == V1 == "cutover_operator_evidence/1"
    assert tuple(pa._REHEARSAL_IMPACTS_BY_CONTRACT) == pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMAS == (V1,)
    assert pa._REHEARSAL_IMPACTS_BY_CONTRACT[V1] is pa._rehearsal_impact_evidence_v1
    with pytest.raises(TypeError):
        pa._REHEARSAL_IMPACTS_BY_CONTRACT["cutover_operator_evidence/2"] = pa._rehearsal_impact_evidence_v1


@pytest.mark.parametrize("unknown", ["cutover_operator_evidence/2", "cutover_operator_evidence/0", "", 1,
                                     ["cutover_operator_evidence/1"], "__class__", "get", b"cutover_operator_evidence/1"])
def test_an_unknown_contract_is_never_computed(unknown):
    with pytest.raises(ValueError, match="unsupported operator-evidence contract"):
        pa.cutover_operator_evidence({}, schema=unknown)


def test_a_stored_comparison_names_its_contract_or_reads_as_unverified():
    assert pa.stored_operator_evidence_schema({"operator_evidence": {"schema": V1}}) == V1
    for stored in (None, [], {}, {"operator_evidence": None}, {"operator_evidence": {}},
                   {"operator_evidence": {"schema": None}}, {"operator_evidence": {"schema": "cutover_operator_evidence/2"}},
                   {"operator_evidence": {"schema": "cutover_operator_evidence"}}, {"operator_evidence": {"schema": 1}},
                   {"operator_evidence": [{"schema": V1}]}):
        assert pa.stored_operator_evidence_schema(stored) is None, stored


_BINDER = "_rehearsal_impact_evidence_v1"
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


def _references(tree, name):
    """Every Name, Attribute and import naming `name` (an alias would be a second route)."""
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name):
            found.append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(a.name == name for a in node.names):
            found.append(node)
    return found


def test_the_frozen_binder_has_exactly_one_reference_the_v1_dispatch_entry():
    """``_rehearsal_impact_evidence_v1`` is reachable only through the /1 entry of the dispatch: no other production
    code can call it, alias it or present its rows."""
    references, dispatch_v1 = [], None
    for rel, path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        references += [(rel, node) for node in _references(tree, _BINDER)]
        if rel == "cisco_toolkit/protocol_assurance.py":
            for stmt in tree.body:
                target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
                    stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
                if isinstance(target, ast.Name) and target.id == _DISPATCH:
                    table = next(n for n in ast.walk(stmt.value) if isinstance(n, ast.Dict))
                    assert len(table.keys) == 1, "the dispatch must hold exactly one contract: /1"
                    for key, value in zip(table.keys, table.values):
                        if isinstance(key, ast.Name) and key.id == "CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1":
                            dispatch_v1 = value
    assert dispatch_v1 is not None, "the /1 entry of _REHEARSAL_IMPACTS_BY_CONTRACT is missing"
    assert [(rel, node.lineno) for rel, node in references] == [
        ("cisco_toolkit/protocol_assurance.py", dispatch_v1.lineno)], references
    assert references[0][1] is dispatch_v1


def test_the_receipt_contract_module_never_reaches_the_engine_owner():
    """The structural half of 'binds evidence only': protocol_assurance (the binder, the dispatch and the payload)
    imports and names nothing of impact_assessability, so no owner change can reach a receipt through it."""
    tree = ast.parse((ROOT / "cisco_toolkit" / "protocol_assurance.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("impact_assessability" in a.name for a in node.names), ast.dump(node)
        elif isinstance(node, ast.ImportFrom):
            assert "impact_assessability" not in (node.module or ""), ast.dump(node)
            assert not any(a.name == "impact_assessability" for a in node.names), ast.dump(node)
        elif isinstance(node, ast.Name):
            assert node.id not in ("ia", "impact_assessability"), node.lineno


# ---------------------------------------------------------------------------------------------------------------
# 3. the interpretation is display-only: never on the receipt or digest path
# ---------------------------------------------------------------------------------------------------------------
_DISPLAY_FIELD = "impacts_view"
_DISPLAY_NAMES = frozenset({"rehearsal_impacts_view", "receipt_impacts_view", "rehearsal_impacts_view_unavailable",
                            "_safe_rehearsal_impacts_view", "_receipts_with_impacts_views", "comparison_after_binding"})
#: The only production units that may produce or name the display field: the engine's view builders and trend
#: pair, and the app's execution-view decorator. Keyed by module path -> allowed top-level/nested function names.
_DISPLAY_PRODUCERS = {
    "webapp/backend/engine.py": {"rehearsal_impacts_view", "receipt_impacts_view", "rehearsal_impacts_view_unavailable",
                                 "_safe_rehearsal_impacts_view", "_impacts_view_cell", "_impacts_view_order",
                                 "comparison_after_binding", "_trend_comparison_receipts"},
    "webapp/backend/app.py": {"_receipts_with_impacts_views", "_execution_view"},
}


def _enclosing_functions(tree):
    """node -> the name of the innermost function that contains it (``None`` at module level)."""
    owner = {}

    def visit(node, current):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            owner[child] = name
            visit(child, name)
    visit(tree, None)
    return owner


def test_the_display_view_never_reaches_the_receipt_or_digest_path():
    """``impacts_view`` and its builders appear only in the engine's view builders/trend pair and in the app's
    execution-view decorator. Storage (writes and re-verification), the comparison composer, the receipt contract,
    the execution state and the PIR export never name them, so the interpretation can be neither stored, hashed nor
    verified."""
    seen = set()
    for rel, path in _production_modules():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=rel)
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Constant) and node.value == _DISPLAY_FIELD:
                hit = _DISPLAY_FIELD
            elif isinstance(node, ast.Name) and node.id in _DISPLAY_NAMES:
                hit = node.id
            elif isinstance(node, ast.Attribute) and node.attr in _DISPLAY_NAMES:
                hit = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _DISPLAY_NAMES:
                hit = node.name
            if hit is None:
                continue
            where = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner.get(node)
            assert rel in _DISPLAY_PRODUCERS and where in _DISPLAY_PRODUCERS[rel], (
                f"{rel}:{getattr(node, 'lineno', '?')} names the display-only {hit!r} inside {where!r}: the live "
                "interpretation must never reach storage, a digest or receipt verification")
            seen.add((rel, where))
    # non-vacuity: the producers exist where the boundary says they are
    assert ("webapp/backend/app.py", "_receipts_with_impacts_views") in seen, seen
    assert ("webapp/backend/engine.py", "_trend_comparison_receipts") in seen, seen
    assert ("webapp/backend/engine.py", "rehearsal_impacts_view") in seen, seen


def test_a_comparison_is_byte_identical_with_and_without_its_display_view():
    """Computing the view neither mutates the comparison nor the snapshot, the comparison's detached envelope still
    verifies, and the same comparison WITH the view inside it would fail that envelope: the view must travel beside
    the comparison, which is exactly where AssessHub puts it."""
    _require_corpus()
    from webapp.backend import engine as web_engine
    from webapp.backend.storage import _comparison_envelope_valid

    raw, snap = _bound("sample")
    comparison = dict(_comparison("sample"))
    before_bytes = pa.canonical_json_bytes(comparison)
    snap_bytes = pa.canonical_json_bytes(snap)
    after = web_engine.comparison_after_binding(comparison)
    assert after == (2, "sha256:" + hashlib.sha256(raw).hexdigest())
    view = web_engine.receipt_impacts_view(comparison, lambda snapshot_id: (snap, {"sha256": after[1]}))
    assert view["available"] is True and view["display_only"] is True and view["source_sha256"] == after[1]
    assert pa.canonical_json_bytes(comparison) == before_bytes
    assert pa.canonical_json_bytes(snap) == snap_bytes
    assert _sha(comparison) == _V1_FROZEN["sample"]["comparison"]
    assert _comparison_envelope_valid(comparison)
    assert not _comparison_envelope_valid({**comparison, _DISPLAY_FIELD: view})
    assert json.dumps(view, allow_nan=False)
