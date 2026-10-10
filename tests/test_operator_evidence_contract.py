"""W50: execution receipts bind failure-impact EVIDENCE; its interpretation is display-only and computed live.

AssessHub persists every execution comparison, its ``operator_evidence`` included, inside an execution comparison
receipt and re-verifies each stored receipt by RECOMPUTING it from the bound snapshots on every read
(``webapp/backend/storage.py``). Anything a receipt binds that is derived from live, evolving code therefore makes
every stored receipt unreadable (409) the day that code changes. So:

1. **The receipt binds evidence only.** ``cutover_operator_evidence/1`` copies the after snapshot's stored
   ``failure_impact`` rows raw into ``rehearsal.impacts`` through one frozen binder
   (``protocol_assurance._rehearsal_impact_evidence_v1``) that never consults the engine owner of row assessability
   (``impact_assessability``): every receipt stored before W50 still verifies, with no migration and no new version.
   No unit the receipt recomputation can reach (from ``compare_bound_pair`` and the storage verifier, through the
   comparison composer, ``html.compute_cutover_gate``, precert and every analyze helper they call) reaches the owner,
   and sabotaging every owner entry point moves no digest.
2. **The dispatch is explicit and fails closed.** ``/1`` is the dispatch's only entry; an unknown, missing or
   non-string contract raises on compute and reads as unverified on a stored receipt.
3. **The interpretation is display-only.** The owner's reading of those rows (``webapp.backend.engine
   .rehearsal_impacts_view``, the API's ``impacts_view``) is computed at request time from the bound snapshot and
   travels BESIDE a comparison, never inside it. No module on the receipt or digest path names it, and putting it
   inside a comparison would fail the detached envelope (shown below), which is why it never goes there.

How the bytes are pinned, and what may ever change a pin
---------------------------------------------------------
Digests use ``protocol_assurance.canonical_json_bytes`` (sorted keys, ASCII, compact). Two kinds of pin exist, and
they answer different questions:

* **The frozen corpus** (``tests/fixtures/operator_evidence_v1/``): four small synthetic snapshots, LF-only and never
  regenerated, whose own SHA-256 is pinned in :data:`_FROZEN_FIXTURES` and asserted before every use. They exercise
  the binder's whole input space -- object rows (a lower bound, a legacy row, a duplicated host, an empty object,
  rows with extra and odd-typed keys: strings for counts, a bool, a null, a negative, a float, an integer past
  2**53, a nested list, an empty key, non-ASCII text), non-object rows of every JSON kind, a missing section and a
  non-list section -- and carry enough of a snapshot (devices, interfaces, cable map, rollback plans and an
  AssessHub-shaped binding with ``script_version``) for :func:`compare_bound_pair` to admit the pair and run the
  whole composer. Because the INPUTS are frozen, a moved digest here can only mean the code moved. **Never re-pin a
  frozen-corpus digest.** A change to the operator-evidence payload needs a new contract
  (``cutover_operator_evidence/2``) with its own frozen binder added BESIDE /1 in the dispatch, so stored /1
  receipts keep verifying; if only ``comparison`` moved, the change is outside this contract and breaks every stored
  receipt alike, so it needs its own receipt-versioning decision. The pins were measured with the pure functions at
  the W50 head, with the deployed ``main`` code (``f797444e``) and with the pre-W50 code (``e7c00e12``), each a
  ``git archive`` imported by path: all three gave every frozen value below
  (``docs/w50-receipt-impacts-validation-2026-10-09.md``).

* **The live corpus** (the committed golden and sample, which ARE regenerated): each pin is an explicit pair,
  ``(corpus_sha256, digests)`` in :data:`_V1_LIVE`, measured at ``e7c00e12`` and unchanged since. While the corpus
  bytes still carry their pinned SHA-256, a moved digest is a code change and is treated exactly like a frozen one.
  When a regeneration changes the corpus bytes, the pair is stale AS A PAIR: re-measure and update the SHA-256 and
  its digests together, in the regeneration's own commit, and only while every frozen-corpus pin above still holds
  (that is what proves the binder did not move with it). Never update a digest without its corpus SHA-256, nor a
  corpus SHA-256 without its digests.

Corpus bytes are read as committed: a ``core.autocrlf=true`` checkout of an unattributed text file (the golden on a
Windows runner) carries CRLF, and :func:`_committed_bytes` undoes exactly that transformation, which is lossless for
JSON (no JSON text holds a literal CR). The frozen fixtures are pinned LF by ``.gitattributes``.

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
FROZEN_CORPUS = ROOT / "tests" / "fixtures" / "operator_evidence_v1"
_CORPUS = {"golden": GOLDEN, "sample": SAMPLE}
V1 = pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1

#: The frozen synthetic corpus: fixture -> the SHA-256 of its committed (LF) bytes. Never regenerated or edited.
_FROZEN_FIXTURES = {
    "before.json": "0ec258031986450de951ccd9b5b7db5954036ca5a0886b7f124704e0bb7273a2",
    "after-rows.json": "08d520724aad77a78cb570837f5a168b586340572d560956dc24651ddb4d4d90",
    "after-missing.json": "d2853c90ec19519f2674d440e2ffa9cb387c8e4cd815e44b0dcc0eec50ab9876",
    "after-non-list.json": "f8e9c8eeccac3b7164edfdd9bcf47401632a37b4e154f82b7d5467782b347932",
}
#: The frozen pairs: name -> (before fixture, after fixture).
_FROZEN_PAIRS = {
    "rows": ("before.json", "after-rows.json"),
    "missing": ("before.json", "after-missing.json"),
    "non_list": ("before.json", "after-non-list.json"),
    "rows_self": ("after-rows.json", "after-rows.json"),
}
#: cutover_operator_evidence/1 and the whole comparison on the frozen corpus (frozen inputs; NEVER re-pin). Measured
#: identically at the W50 head, with the deployed main (f797444e) and with the pre-W50 code (e7c00e12). ``missing``
#: and ``non_list`` share their operator-evidence digest by design: both bind no row, and nothing else differs.
_V1_FROZEN_CORPUS = {
    "rows": {
        "operator_evidence": "8914d60065a45a2ea78f160363c828d4c540d90b9c4a9a151e0bbaa5d746a600",
        "comparison": "8f998baaf7f79fa29f431c9f4d8d7319cc3bb363dc640ef7532e9dc4bbda4823",
    },
    "missing": {
        "operator_evidence": "5c7939b2b6aab6dc97724ffed99a122b05bd4cf55d0d63fa69302a6bff1190e7",
        "comparison": "4b05de8cb3a2f1e16f305b5bddfa57ab54e5712f18ab5dbb5398341d6c85a403",
    },
    "non_list": {
        "operator_evidence": "5c7939b2b6aab6dc97724ffed99a122b05bd4cf55d0d63fa69302a6bff1190e7",
        "comparison": "bb2de4a7a65a2d0918d65253a9eb13bd41c3e9e20342547a3aed83999dcbe17d",
    },
    "rows_self": {
        "operator_evidence": "8914d60065a45a2ea78f160363c828d4c540d90b9c4a9a151e0bbaa5d746a600",
        "comparison": "34ecb7e30cd4d77f425b34acc0858b636403021ca32602d5b435eae70fcb6cf1",
    },
}
#: cutover_operator_evidence/1 on the LIVE corpus as the pre-W50 engine computed it (measured at e7c00e12), each an
#: explicit pair: the corpus SHA-256 the digests were measured on, then the digests. A regeneration updates the pair
#: together; a code change with the corpus unchanged fails (module docstring).
#: W52 / G14: the committed golden and sample now carry G14's hosted-regenerated vlan_carriage section, so both pairs
#: were re-measured together with the pure functions on those committed bytes, after the frozen-corpus pins were
#: confirmed on the same tree. The previous pairs (golden c4f6a549.../9da4d736.../56b1c51c..., sample
#: dbc229cf.../ab1f6d46.../0c81ec19...) still reproduce exactly when this tree's code reads the previous corpus bytes,
#: so no code moved a stored-receipt digest; operator_evidence is unchanged and only the corpus moved comparison.
_V1_LIVE = {
    "golden": {
        "corpus_sha256": "fc8cf44f3d83a854f5d7523e127086faa138e4483a7553c28cbecfba1be180a3",
        "operator_evidence": "9da4d736cb8c1bfbe6ed4fe69c4ea01bacfd40ed2a353b50fa7368e8d3f75557",
        "comparison": "c1a2e269ec27d51c6f6e2a2ac3f4510b34951684c62cdda704c9b422ef9bc268",
    },
    "sample": {
        "corpus_sha256": "d015e974606ca78d623f1e9547df82e9a316708506be3438f59151342a22026a",
        "operator_evidence": "ab1f6d468e57cba53658dff2af81baa25498fcf674f805d3a783dcd83c7c7b32",
        "comparison": "06acd1342e4347ae367443ace56e01a0d39c8b7edabeffecd037dd66c0c8543c",
    },
}


def _sha(value) -> str:
    return hashlib.sha256(pa.canonical_json_bytes(value)).hexdigest()


def _committed_bytes(path: pathlib.Path) -> bytes:
    """The file's committed bytes: a CRLF checkout (``core.autocrlf=true`` on an unattributed text file) is undone,
    which is lossless for JSON; any other CR fails rather than being guessed at."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    assert b"\r" not in raw, f"{path.name} carries a CR that is not a CRLF line ending"
    return raw


def _frozen(name: str) -> bytes:
    """One frozen fixture's bytes, checked against its pinned SHA-256 before any use."""
    raw = _committed_bytes(FROZEN_CORPUS / name)
    assert hashlib.sha256(raw).hexdigest() == _FROZEN_FIXTURES[name], (
        f"frozen fixture {name} changed: the frozen corpus is never edited or regenerated (module docstring)")
    return raw


def _bound(name):
    raw = _committed_bytes(_CORPUS[name])
    return raw, pa.bind_snapshot_json_bytes(raw)


def _binding(raw: bytes, snapshot_id: int, script_version=None) -> dict:
    """The fixed persisted-source binding the pins were measured with. The live pins were measured without
    ``script_version`` (as at e7c00e12); the frozen corpus carries it, as AssessHub's stored binding does
    (``storage._snapshot_binding_from_row``), so its pairs are admitted and the whole composer runs."""
    binding = {
        "snapshot_id": snapshot_id,
        "campaign_id": 1,
        "engagement_id": "E",
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "source": pa.PERSISTED_SOURCE,
        "label": "x",
    }
    if script_version is not None:
        binding["script_version"] = script_version
    return binding


def _comparison(name: str, contract=None):
    raw, snap = _bound(name)
    kwargs = {} if contract is None else {"operator_evidence_schema": contract}
    return compare_bound_pair(snap, snap, before_binding=_binding(raw, 1), after_binding=_binding(raw, 2), **kwargs)


def _digests(name: str, contract=None) -> dict:
    """The operator-evidence and full-comparison digests of one live-corpus snapshot (``contract`` None: the
    default), with the SHA-256 of the corpus bytes they were computed on."""
    raw, snap = _bound(name)
    kwargs = {} if contract is None else {"schema": contract}
    evidence = pa.cutover_operator_evidence(snap, prior_snapshot=snap, **kwargs)
    assert evidence["schema"] == V1
    comparison = _comparison(name, contract)
    assert comparison["operator_evidence"] == evidence
    return {"corpus_sha256": hashlib.sha256(raw).hexdigest(),
            "operator_evidence": _sha(evidence), "comparison": _sha(dict(comparison))}


def _frozen_digests(pair: str, contract=None) -> dict:
    """The operator-evidence and full-comparison digests of one frozen pair (``contract`` None: the default)."""
    before_name, after_name = _FROZEN_PAIRS[pair]
    before_raw, after_raw = _frozen(before_name), _frozen(after_name)
    before, after = pa.bind_snapshot_json_bytes(before_raw), pa.bind_snapshot_json_bytes(after_raw)
    kwargs = {} if contract is None else {"schema": contract}
    evidence = pa.cutover_operator_evidence(after, prior_snapshot=before, **kwargs)
    assert evidence["schema"] == V1
    comparison = compare_bound_pair(
        before, after,
        before_binding=_binding(before_raw, 1, before["script_version"]),
        after_binding=_binding(after_raw, 2, after["script_version"]),
        **({} if contract is None else {"operator_evidence_schema": contract}))
    assert comparison["operator_evidence"] == evidence
    assert comparison["comparison_admission"]["status"] == "admitted", comparison["comparison_admission"]
    return {"operator_evidence": _sha(evidence), "comparison": _sha(dict(comparison))}


def _require_corpus():
    missing = [str(path) for path in _CORPUS.values() if not path.exists()]
    if missing:
        pytest.skip(f"corpus snapshot not present: {missing}")


def _assert_live_pair(name: str, measured: dict) -> None:
    pinned = _V1_LIVE[name]
    assert measured["corpus_sha256"] == pinned["corpus_sha256"], (
        f"the {name} corpus was regenerated (its bytes no longer carry the SHA-256 the /1 digests were measured on). "
        "Re-measure and update the corpus_sha256 AND its digests together in _V1_LIVE, only while every frozen-corpus "
        "pin still holds (module docstring)")
    assert measured == pinned, (
        "cutover_operator_evidence/1 no longer recomputes the bytes the pre-W50 engine stored for an UNCHANGED "
        "corpus, so every stored receipt would fail re-verification. Restore _rehearsal_impact_evidence_v1 and the "
        "shared payload; if only 'comparison' moved, a change outside this contract breaks every stored receipt "
        "(module docstring).")


# ---------------------------------------------------------------------------------------------------------------
# 1. the receipt binds frozen evidence, independent of the owner
# ---------------------------------------------------------------------------------------------------------------
def test_the_frozen_corpus_is_intact_and_lf_only():
    """The inputs of every frozen pin: exactly these four fixtures, each byte-identical to its pin and LF-only on disk
    (``.gitattributes`` pins them LF), and together they exercise the binder's input space."""
    assert sorted(p.name for p in FROZEN_CORPUS.glob("*.json")) == sorted(_FROZEN_FIXTURES)
    for name in _FROZEN_FIXTURES:
        assert b"\r" not in (FROZEN_CORPUS / name).read_bytes(), name
        _frozen(name)
    rows = json.loads(_frozen("after-rows.json"))["failure_impact"]
    kinds = {type(row).__name__ for row in rows}
    assert {"dict", "str", "int", "NoneType", "list", "bool"} <= kinds, kinds
    odd = next(row for row in rows if isinstance(row, dict) and row.get("host") == "fx-acc-c")
    assert {"extra_key", "", "note"} <= set(odd) and odd["blind_links"] > 2 ** 53, odd
    assert {} in rows
    assert "failure_impact" not in json.loads(_frozen("after-missing.json"))
    assert isinstance(json.loads(_frozen("after-non-list.json"))["failure_impact"], dict)


@pytest.mark.parametrize("contract", [None, V1])
@pytest.mark.parametrize("pair", sorted(_FROZEN_PAIRS))
def test_v1_recomputes_the_frozen_bytes_on_the_frozen_corpus(pair, contract):
    """The binder's pin on inputs that never change: a moved digest here is a code change, never a corpus one."""
    assert _frozen_digests(pair, contract) == _V1_FROZEN_CORPUS[pair], (
        "cutover_operator_evidence/1 no longer recomputes its frozen bytes on the FROZEN corpus. Never re-pin: "
        "restore _rehearsal_impact_evidence_v1 and the shared payload, or add a new contract beside /1 "
        "(module docstring).")


@pytest.mark.parametrize("contract", [None, V1])
@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_v1_recomputes_the_pinned_bytes_on_the_live_corpus(name, contract):
    """Every receipt stored before W50 keeps verifying only while /1 recomputes exactly what the pre-W50 engine wrote,
    both as the default a new comparison carries and as the contract a stored receipt declares. Each pin is a
    (corpus SHA-256, digests) pair: a regeneration updates both, a code change cannot."""
    _require_corpus()
    _assert_live_pair(name, _digests(name, contract))


def _sabotage_the_owner(monkeypatch):
    """Make every engine-owner entry point raise and change one of its decisions (the reviewers' counterexample:
    'endpoint' leaves IMPACT_EDGE_KINDS, which moves verdicts on a real fleet)."""
    def touched(*_args, **_kwargs):
        raise AssertionError("the receipt path consulted the engine owner of row assessability")

    monkeypatch.setattr(ia, "IMPACT_EDGE_KINDS", frozenset({"ap", "phone"}))
    for name in ("assess_failure_impact", "rows_with_verdicts", "assessment_document", "row_hold", "off_scan_bound",
                 "blind_bound", "neighbour_bound", "duplicate_doubt", "table_value", "table_detail", "ranked_value",
                 "ranks", "ranking_floor", "ranking_order", "unranked", "cell_reading", "disclose", "section_state",
                 "count_value"):
        monkeypatch.setattr(ia, name, touched)
    monkeypatch.setattr(ia, "CODE_PHRASES", type(ia.CODE_PHRASES)(
        {code: "REWORDED " + phrase for code, phrase in ia.CODE_PHRASES.items()}))


@pytest.mark.parametrize("pair", sorted(_FROZEN_PAIRS))
def test_no_owner_change_can_move_a_frozen_receipt(pair, monkeypatch):
    """The failure that drove the pivot: an owner-valued receipt tracks every owner change, so the next change to what
    the owner decides (or how it words it) would make stored receipts unreadable. The receipt binds evidence only, so
    with every owner entry point sabotaged the whole comparison recomputes the same frozen bytes."""
    _sabotage_the_owner(monkeypatch)
    assert _frozen_digests(pair) == _V1_FROZEN_CORPUS[pair]


@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_no_owner_change_can_move_a_stored_receipt(name, monkeypatch):
    """The same on the live corpus, read through its (corpus SHA-256, digests) pair."""
    _require_corpus()
    _sabotage_the_owner(monkeypatch)
    _assert_live_pair(name, _digests(name))


def test_the_evidence_binder_copies_the_frozen_rows_raw_whatever_their_shape():
    """On the frozen corpus: every object row in stored order, raw (odd types, extra keys, the empty object and the
    duplicated host included), no non-object row, and nothing at all for a missing or a non-list section."""
    rows = json.loads(_frozen("after-rows.json"))["failure_impact"]
    objects = [row for row in rows if isinstance(row, dict)]
    assert len(objects) == 6 and len(rows) == 11, rows
    for after_name, expected in (("after-rows.json", objects), ("after-missing.json", []),
                                 ("after-non-list.json", [])):
        snap = pa.bind_snapshot_json_bytes(_frozen(after_name))
        rehearsal = pa.cutover_operator_evidence(snap)["rehearsal"]
        assert rehearsal["impacts"] == expected, after_name
        assert rehearsal["n_impacts_total"] == len(expected), after_name


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
    """The module-level half of 'binds evidence only': protocol_assurance (the binder, the dispatch and the payload)
    imports and names nothing of impact_assessability. The closure check below covers everything else a receipt
    recomputation runs."""
    tree = ast.parse((ROOT / "cisco_toolkit" / "protocol_assurance.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("impact_assessability" in a.name for a in node.names), ast.dump(node)
        elif isinstance(node, ast.ImportFrom):
            assert "impact_assessability" not in (node.module or ""), ast.dump(node)
            assert not any(a.name == "impact_assessability" for a in node.names), ast.dump(node)
        elif isinstance(node, ast.Name):
            assert node.id not in ("ia", "impact_assessability"), node.lineno


#: Where a receipt recomputation starts: the comparison composer (engine delegate and owner), and the two storage
#: verifiers that recompute a stored receipt and admit a new one. Everything they reach is the receipt-recompute
#: closure: the comparison composer, html.compute_snapshot_delta / compute_cutover_gate, precert, the protocol and L2
#: owners, and every analyze helper those call.
_RECOMPUTE_ROOTS = (
    ("cisco_toolkit.comparison", "compare_bound_pair"),
    ("webapp.backend.engine", "compare_bound_pair"),
    ("webapp.backend.storage", "Store._execution_receipt_authority_locked"),
    ("webapp.backend.storage", "Store.append_execution_comparison_if_unchanged"),
)


def test_the_receipt_recompute_closure_never_reaches_the_engine_owner():
    """The structural half of 'binds evidence only', over the WHOLE closure a receipt recomputation can execute: a
    static call graph from :data:`_RECOMPUTE_ROOTS` (resolved calls and references, ``module.function`` attributes,
    ``self.method``, module-level dispatch tables, and every method of each project class a unit names) reaches no
    unit that is, imports or names ``impact_assessability``. The graph is the W48 guard's resolver
    (``tests/test_impact_consumers.py :: _graph``); its scope limits are stated there, and the sabotage tests above
    are the runtime half."""
    import test_impact_consumers as consumers

    graph = consumers._graph(str(ROOT))
    for root in _RECOMPUTE_ROOTS:
        assert root in graph.units, root
    closure = consumers._closure(graph, _RECOMPUTE_ROOTS)
    reached = sorted(unit for unit in closure if unit in graph.direct or unit in graph.owner_refs)
    assert not reached, ("the receipt recomputation reaches the engine owner of row assessability, so an owner change "
                         "would move a stored receipt: " + "; ".join(consumers._path(closure, u) for u in reached))
    # non-vacuity: the closure is the recompute, not a stub of it
    for unit in (("cisco_toolkit.html", "compute_snapshot_delta"), ("cisco_toolkit.html", "compute_cutover_gate"),
                 ("cisco_toolkit.precert", "compute_precert"),
                 ("cisco_toolkit.protocol_assurance", "cutover_operator_evidence"),
                 ("cisco_toolkit.protocol_assurance", _BINDER),
                 ("cisco_toolkit.protocol_assurance", "compute_native_protocol_deltas"),
                 ("cisco_toolkit.l2_rehearsal", "compute_l2_failure_rehearsal"),
                 ("cisco_toolkit.l2_rehearsal", "compute_observed_l2_failure_evidence"),
                 ("webapp.backend.engine", "compact_execution_comparison"),
                 ("webapp.backend.engine", "stored_operator_evidence_contract")):
        assert unit in closure, unit
    assert any(module == "cisco_toolkit.analyze" for module, _name in closure)
    # ... and the display path, which DOES read the owner, is outside it
    assert ("webapp.backend.engine", "rehearsal_impacts_view") in graph.direct
    assert ("webapp.backend.engine", "rehearsal_impacts_view") not in closure


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_closure_check_sees_each_route_to_the_owner(tmp_path):
    """Non-vacuity on a synthetic tree: each route by which a recomputation could reach the owner is seen -- a helper
    two calls deep, a project class whose method uses the owner, an unaliased dotted import, and a dispatch table --
    and an unrelated owner user outside the closure is not."""
    import test_impact_consumers as consumers

    _write(tmp_path, "cisco_toolkit/__init__.py", "")
    _write(tmp_path, "cisco_toolkit/impact_assessability.py", "def ranks(v):\n    return True\n")
    _write(tmp_path, "cisco_toolkit/html.py",
           "from cisco_toolkit import impact_assessability as ia\n"
           "def _deep(v):\n    return ia.ranks(v)\n"
           "def _helper(v):\n    return _deep(v)\n"
           "def compute_cutover_gate(v):\n    return _helper(v)\n"
           "def explorer(v):\n    return ia.ranks(v)\n")
    _write(tmp_path, "cisco_toolkit/widgets.py",
           "class Widget:\n    def __init__(self, v):\n        self.v = v\n"
           "    def score(self):\n        from cisco_toolkit.impact_assessability import ranks\n"
           "        return ranks(self.v)\n")
    _write(tmp_path, "cisco_toolkit/dotted.py",
           "def lookup(v):\n    import cisco_toolkit.impact_assessability\n"
           "    return cisco_toolkit.impact_assessability.ranks(v)\n")
    _write(tmp_path, "cisco_toolkit/table.py",
           "from cisco_toolkit import dotted\n"
           "_BY = {'x': dotted.lookup}\n"
           "def pick(v):\n    return _BY['x'](v)\n")
    _write(tmp_path, "cisco_toolkit/comparison.py",
           "from cisco_toolkit import html as _html\n"
           "from cisco_toolkit.widgets import Widget\n"
           "from cisco_toolkit import table\n"
           "def compare_bound_pair(v):\n"
           "    return _html.compute_cutover_gate(v), Widget(v), table.pick(v)\n"
           "def clean(v):\n    return v\n")
    graph = consumers._graph(str(tmp_path))

    def reached(root):
        closure = consumers._closure(graph, [root])
        return {f"{m}:{n}" for (m, n) in closure if (m, n) in graph.direct or (m, n) in graph.owner_refs}

    assert reached(("cisco_toolkit.comparison", "compare_bound_pair")) == {
        "cisco_toolkit.html:_deep", "cisco_toolkit.widgets:Widget.score", "cisco_toolkit.dotted:lookup",
        "cisco_toolkit.impact_assessability:ranks"}
    assert reached(("cisco_toolkit.comparison", "clean")) == set()
    assert "cisco_toolkit.html:explorer" not in reached(("cisco_toolkit.comparison", "compare_bound_pair"))


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
                                 "_safe_rehearsal_impacts_view", "comparison_after_binding",
                                 "_trend_comparison_receipts"},
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
    _assert_live_pair("sample", {"corpus_sha256": hashlib.sha256(raw).hexdigest(),
                                 "operator_evidence": _sha(comparison["operator_evidence"]),
                                 "comparison": _sha(comparison)})
    assert _comparison_envelope_valid(comparison)
    assert not _comparison_envelope_valid({**comparison, _DISPLAY_FIELD: view})
    assert json.dumps(view, allow_nan=False)
