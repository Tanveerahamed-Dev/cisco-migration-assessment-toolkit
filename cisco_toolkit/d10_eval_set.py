"""D10 Phase-2 eval set — extractor, loaders and validators for the 60-query fixture (P2-1).

The retrieval-layer falsification run (docs/architect-master-plan-2026-07-10.md §5 Phase 2; protocol
owner docs/d10-retrieval-eval-design-2026-07-08.md §2–§4 + the DEC-006 amendment) needs a committed,
frozen eval set BEFORE any run: 20 identifier + 20 semantic + 10 multi-hop + 10 negative queries with
graded 0–3 qrels, plus 15 anchor queries whose expected grades are SEALED from the judge under test.
This module is the one implementation of that fixture's contract:

* **Identifier stratum — extracted, not authored.** :func:`extract_identifier_queries` derives the 20
  identifier queries from ``graphify-out/graph.json`` (owner doc §2: the AST labels are "free and
  exactly correct"). Deterministic by construction — no randomness, no clock: candidates are python
  code symbols whose label is UNIQUE among code nodes (an ambiguous label cannot be "exactly correct
  by construction"), ranked by CROSS-FILE reference in-degree (links in :data:`REFERENCE_RELATIONS`
  whose endpoints live in different files — intra-file fan-in would rank test helpers over engine
  hubs), ties broken by label. Same graph bytes in → same 20 rows out.
* **Authored strata are frozen data, not code.** The semantic / multi-hop / negative rows and the
  anchors live in the committed JSONL fixtures (docs/quality/) — this module VALIDATES them; it never
  regenerates them. Strata counts are read from the P2-0d pre-registration
  (``docs/quality/d10-eval-thresholds.json :: query_set`` — the count owner; Law 1: reconcile, never
  restate).
* **The anchor answer key is sealed by SEPARATION** (the :mod:`cisco_toolkit.defect_panel` pattern:
  the judge sees the panel text, the key goes only to ``score_verdicts``). Here the judge-visible
  half (:func:`load_anchors`) carries ONLY ``aid``/``query``/``doc``; the expected grades live in a
  separate key file (:func:`load_anchor_key`) that must never enter a judge prompt — it is consumed
  only by the P2-2 screening-gate scorer. Tamper-evidence is an exact SHA-256 pin in
  ``tests/test_d10_eval_set.py`` (the d10-thresholds pin idiom): any edit must move fixture and pin
  together in a reviewed diff. Declared residual: the key is plaintext in the repo — the seal is
  separation + tamper-evidence + pre-registration, not secrecy (same honesty as the holdout contract).

Offline, stdlib-only, no egress, no device contact. The graph lives only on the owner machine
(``graphify-out/`` is gitignored — the worktree trap), so every graph-dependent check degrades to an
explicit "graph not reachable" rather than a fabricated pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Reference-type relations — an artifact LEANING on another. Structural relations (``contains``,
# ``method``, ``defines``) and docstring links (``rationale_for``) are deliberately excluded: they
# describe layout, not use, and would let a file's own scaffolding inflate its rank.
REFERENCE_RELATIONS = frozenset(
    {"calls", "indirect_call", "imports", "imports_from", "references", "uses", "inherits",
     "re_exports"})

STRATA: Tuple[str, ...] = ("identifier", "semantic", "multi_hop", "negative")
QID_PREFIX = {"identifier": "I", "semantic": "S", "multi_hop": "M", "negative": "N"}
ANCHOR_CLASSES: Tuple[str, ...] = ("clear_relevant", "clear_irrelevant", "borderline")
# Pre-registered accuracy bands per anchor class (frozen with the key; adjusting one after any judge
# run is a §7-class protocol violation). clear_irrelevant is strict {0} on purpose: ANY relevance
# credit to a clearly-irrelevant doc is exactly the agreeableness failure the screening gate exists
# to catch; clear_relevant admits 2 because the dual-prompt take-the-MIN ensemble (owner doc §6)
# biases grades down; borderline sits on the 1–2 boundary by construction.
ANCHOR_BANDS = {"clear_relevant": {2, 3}, "clear_irrelevant": {0}, "borderline": {1, 2}}

# Judge-visible anchor fields — EXACTLY these; anything more is answer leakage into the judge's
# half of the sealed pair (the seal test pins this).
ANCHOR_FIELDS = {"aid", "query", "doc"}

GRADES = (0, 1, 2, 3)
DIGEST_DOC = re.compile(r"^digest:[a-z0-9][a-z0-9-]*$")

EVAL_SET_PATH = os.path.join("docs", "quality", "d10-eval-set.jsonl")
ANCHORS_PATH = os.path.join("docs", "quality", "d10-anchors.jsonl")
ANCHOR_KEY_PATH = os.path.join("docs", "quality", "d10-anchor-key.jsonl")
THRESHOLDS_PATH = os.path.join("docs", "quality", "d10-eval-thresholds.json")


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- fixture I/O ---------------------------------------------------------------------------------

def _read_jsonl(path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Read a fixture: first line is the ``{"_meta": …}`` header, the rest are rows."""
    meta: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if i == 0 and "_meta" in obj:
                meta = obj["_meta"]
            else:
                rows.append(obj)
    return meta, rows


def load_eval_set(root: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    return _read_jsonl(os.path.join(root or _root(), EVAL_SET_PATH))


def load_anchors(root: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The judge-visible half of the anchor set — safe to place in a judge prompt."""
    return _read_jsonl(os.path.join(root or _root(), ANCHORS_PATH))


def load_anchor_key(root: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The SEALED half — expected grades. Scorer-only (defect_panel ``score_verdicts`` pattern):
    never load this in any prompt-building path; the P2-2 screening gate compares the judge's anchor
    grades against it AFTER the judge has answered."""
    return _read_jsonl(os.path.join(root or _root(), ANCHOR_KEY_PATH))


def load_thresholds(root: Optional[str] = None) -> Dict[str, Any]:
    with open(os.path.join(root or _root(), THRESHOLDS_PATH), encoding="utf-8") as f:
        return json.load(f)


def sha256_normalized(path: str) -> str:
    """SHA-256 of the file's text with line endings normalized to ``\\n`` — the tamper-evidence pin
    target. Normalization keeps the pin identical whether git checked the file out LF or CRLF."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# --- the identifier-stratum extractor (deterministic, graph-in → rows-out) -------------------------

def extract_identifier_queries(graph: Dict[str, Any], n: int = 20) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Derive the identifier stratum from a loaded ``graph.json`` dict. Pure and deterministic:
    no clock, no randomness, no environment reads — reproducibility is by construction, which is
    what "seed-fixed" demands here.

    Rules (each declared, none tunable): candidate = python code node with a label UNIQUE among all
    code nodes; rank = number of :data:`REFERENCE_RELATIONS` links from a DIFFERENT source file
    (cross-file in-degree); ties by label ascending; top ``n``. qrels per owner doc §2: the defining
    file grade 3, every cross-file reference-neighbour file grade 1.
    """
    nodes: Dict[str, Dict[str, Any]] = {nd["id"]: nd for nd in graph.get("nodes", [])}
    label_count: Dict[str, int] = {}
    for nd in graph.get("nodes", []):
        if nd.get("file_type") == "code":
            lab = str(nd.get("label", ""))
            label_count[lab] = label_count.get(lab, 0) + 1

    def _candidate(nd: Dict[str, Any]) -> bool:
        lab = str(nd.get("label", ""))
        src = str(nd.get("source_file", ""))
        return (nd.get("file_type") == "code" and src.endswith(".py")
                and not lab.endswith(".py") and label_count.get(lab, 0) == 1)

    indeg: Dict[str, int] = {}
    neigh: Dict[str, set] = {}
    for link in graph.get("links", []):
        if link.get("relation") not in REFERENCE_RELATIONS:
            continue
        s, t = nodes.get(link.get("source")), nodes.get(link.get("target"))
        if not s or not t:
            continue
        sf, tf = str(s.get("source_file", "")), str(t.get("source_file", ""))
        if sf == tf:
            continue
        indeg[t["id"]] = indeg.get(t["id"], 0) + 1
        neigh.setdefault(t["id"], set()).add(sf)
        neigh.setdefault(s["id"], set()).add(tf)

    ranked = sorted(
        ((deg, nid) for nid, deg in indeg.items() if nid in nodes and _candidate(nodes[nid])),
        key=lambda pair: (-pair[0], str(nodes[pair[1]].get("label", ""))))

    commit = str(graph.get("built_at_commit", ""))
    rows: List[Dict[str, Any]] = []
    for rank, (deg, nid) in enumerate(ranked[:n], start=1):
        nd = nodes[nid]
        sym = str(nd.get("label", ""))
        own = str(nd.get("source_file", ""))
        neighbours = sorted(f for f in neigh.get(nid, ()) if f and f != own)
        qrels = [{"doc": own, "grade": 3, "why": f"defining file of `{sym}` (graph node {nid})"}]
        qrels += [{"doc": f, "grade": 1, "why": f"cross-file reference neighbour of `{sym}`"}
                  for f in neighbours]
        rows.append({
            "qid": f"I-{rank:02d}",
            "stratum": "identifier",
            "query": f"what does `{sym}` do?",
            "symbol": sym,
            "node_id": nid,
            "in_degree": deg,
            "qrels": qrels,
            "grounding": f"graphify-out/graph.json @ {commit} :: node {nid} "
                         f"(cross-file reference in-degree {deg}; label unique among code nodes)",
        })
    provenance = {
        "built_at_commit": commit,
        "nodes": len(graph.get("nodes", [])),
        "links": len(graph.get("links", [])),
    }
    return rows, provenance


def find_graph_json(root: Optional[str] = None) -> Optional[str]:
    """Locate ``graphify-out/graph.json`` — worktree-aware. The graph is gitignored and exists only
    on the owner machine's MAIN checkout (the graphify-out worktree trap), so from a linked worktree
    we resolve the main checkout via ``git rev-parse --git-common-dir``. Returns ``None`` when no
    graph is reachable (clean clone / CI) — callers must degrade explicitly, never fabricate."""
    base = root or _root()
    local = os.path.join(base, "graphify-out", "graph.json")
    if os.path.exists(local):
        return local
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=base,
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            git_dir = out.stdout.strip()
            if not os.path.isabs(git_dir):
                git_dir = os.path.abspath(os.path.join(base, git_dir))
            main = os.path.join(os.path.dirname(git_dir), "graphify-out", "graph.json")
            if os.path.exists(main):
                return main
    except Exception:
        pass
    return None


# --- validators (the one implementation — tests call these, the CLI calls these) -------------------

def _name_tokens(doc: str) -> set:
    """Identifier-ish tokens (length ≥ 4) of a qrel target's NAME — the tokens a synonym-stripped
    semantic query must not reuse (owner doc §2: "reject any query reusing a node token").
    ``cisco_toolkit/memory_guard.py`` → {memory, guard}; ``digest:coverage-honesty-002`` →
    {coverage, honesty}."""
    name = doc.split(":", 1)[1] if doc.startswith("digest:") else os.path.basename(doc)
    name = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    name = re.sub(r"-\d+$", "", name)
    parts = re.split(r"[-_.\s]+", name)
    toks: set = set()
    for part in parts:
        toks.update(m.group(0).lower() for m in re.finditer(r"[A-Za-z][a-z0-9]*", part))
    return {t for t in toks if len(t) >= 4}


def _query_tokens(query: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 4}


def validate_eval_set(meta: Dict[str, Any], rows: List[Dict[str, Any]],
                      thresholds: Dict[str, Any], root: Optional[str] = None) -> List[str]:
    """Return the list of contract violations (empty == valid). Counts reconcile to the P2-0d
    pre-registration's ``query_set`` (the owner); everything else is the P2-1 row contract."""
    base = root or _root()
    problems: List[str] = []
    want = dict(thresholds.get("query_set", {}))
    want.pop("anchors_separate", None)

    got: Dict[str, int] = {}
    seen_qids: set = set()
    for row in rows:
        stratum = row.get("stratum")
        got[stratum] = got.get(stratum, 0) + 1
        qid = str(row.get("qid", ""))
        if qid in seen_qids:
            problems.append(f"{qid}: duplicate qid")
        seen_qids.add(qid)
        if stratum not in STRATA:
            problems.append(f"{qid}: unknown stratum {stratum!r}")
            continue
        if not qid.startswith(QID_PREFIX[stratum] + "-"):
            problems.append(f"{qid}: qid prefix does not match stratum {stratum}")
        if not str(row.get("query", "")).strip():
            problems.append(f"{qid}: empty query")

        qrels = row.get("qrels")
        if not isinstance(qrels, list):
            problems.append(f"{qid}: qrels must be a list")
            continue
        for qr in qrels:
            doc, grade = qr.get("doc"), qr.get("grade")
            if not str(doc or "").strip():
                problems.append(f"{qid}: qrel with empty doc")
                continue
            if grade not in GRADES:
                problems.append(f"{qid}: qrel grade {grade!r} outside 0-3 ({doc})")
            if not str(qr.get("why", "")).strip():
                problems.append(f"{qid}: qrel for {doc} carries no 'why'")
            if str(doc).startswith("digest:"):
                if not DIGEST_DOC.match(str(doc)):
                    problems.append(f"{qid}: malformed digest doc id {doc!r}")
                if not row.get("requires_digest"):
                    problems.append(f"{qid}: digest qrel but requires_digest is not true")
            elif not os.path.exists(os.path.join(base, str(doc))):
                problems.append(f"{qid}: qrel doc does not exist on disk: {doc}")

        if stratum == "identifier":
            sym = str(row.get("symbol", ""))
            if not sym:
                problems.append(f"{qid}: identifier row without symbol")
            elif f"`{sym}`" not in str(row.get("query", "")):
                problems.append(f"{qid}: identifier query does not quote its symbol `{sym}`")
            if not str(row.get("node_id", "")).strip():
                problems.append(f"{qid}: identifier row without node_id provenance")
            if not any(qr.get("grade") == 3 for qr in qrels):
                problems.append(f"{qid}: identifier row has no grade-3 qrel")
        else:
            if not str(row.get("grounding", "")).strip():
                problems.append(f"{qid}: non-identifier row carries no grounding citation")

        if stratum == "semantic":
            primaries = [qr for qr in qrels if qr.get("grade") == 3]
            if not primaries:
                problems.append(f"{qid}: semantic row has no grade-3 qrel")
            qtoks = _query_tokens(str(row.get("query", "")))
            for qr in primaries:
                overlap = qtoks & _name_tokens(str(qr.get("doc", "")))
                if overlap:
                    problems.append(f"{qid}: semantic query reuses target name token(s) "
                                    f"{sorted(overlap)} of {qr.get('doc')} (synonym-strip rule)")

        if stratum == "multi_hop":
            edges = row.get("edges")
            if not isinstance(edges, list) or len(edges) < 2:
                problems.append(f"{qid}: multi-hop row must declare >= 2 graph edges")
            else:
                for e in edges:
                    missing = [k for k in ("source", "source_file", "relation", "target",
                                           "target_file") if not str(e.get(k, "")).strip()]
                    if missing:
                        problems.append(f"{qid}: edge missing fields {missing}")
                    elif e.get("relation") not in REFERENCE_RELATIONS:
                        problems.append(f"{qid}: edge relation {e.get('relation')!r} is not a "
                                        f"reference relation")

        if stratum == "negative" and row.get("qrels"):
            problems.append(f"{qid}: negative row must have EMPTY qrels (unanswerable by "
                            f"construction)")

        if row.get("requires_digest") and "gitignor" not in str(row.get("grounding", "")):
            problems.append(f"{qid}: digest-lane row's grounding must say the digest is "
                            f"gitignored/owner-machine (DEC-006 A2 honesty)")

    for stratum, count in sorted(want.items()):
        if got.get(stratum, 0) != count:
            problems.append(f"stratum {stratum}: {got.get(stratum, 0)} rows, pre-registration "
                            f"requires exactly {count}")
    extra = sorted(set(got) - set(want))
    if extra:
        problems.append(f"unregistered strata present: {extra}")
    return problems


def validate_anchors(anchor_rows: List[Dict[str, Any]], key_rows: List[Dict[str, Any]],
                     thresholds: Dict[str, Any], root: Optional[str] = None) -> List[str]:
    """The anchor contract: judge-visible half sealed (whitelist fields only), key half complete
    (exact aid coverage, 5/5/5 class split, bands matching the pre-registered mapping)."""
    base = root or _root()
    problems: List[str] = []
    want = int(thresholds.get("query_set", {}).get("anchors_separate", 0))
    if len(anchor_rows) != want:
        problems.append(f"anchors: {len(anchor_rows)} rows, pre-registration requires {want}")

    aids: List[str] = []
    for row in anchor_rows:
        aid = str(row.get("aid", ""))
        aids.append(aid)
        extra = set(row) - ANCHOR_FIELDS
        if extra:
            problems.append(f"{aid}: judge-visible anchor carries non-whitelisted field(s) "
                            f"{sorted(extra)} — answer leakage breaks the seal")
        missing = [f for f in ANCHOR_FIELDS if not str(row.get(f, "")).strip()]
        if missing:
            problems.append(f"{aid}: anchor missing {missing}")
        doc = str(row.get("doc", ""))
        if doc and not os.path.exists(os.path.join(base, doc)):
            problems.append(f"{aid}: anchor doc does not exist on disk: {doc}")
    if len(set(aids)) != len(aids):
        problems.append("anchors: duplicate aids")

    key_by_aid = {str(k.get("aid", "")): k for k in key_rows}
    if set(key_by_aid) != set(aids):
        problems.append(f"anchor key does not cover exactly the anchor aids "
                        f"(key-only: {sorted(set(key_by_aid) - set(aids))}; "
                        f"unkeyed: {sorted(set(aids) - set(key_by_aid))})")
    classes: Dict[str, int] = {}
    for aid, k in sorted(key_by_aid.items()):
        cls = str(k.get("class", ""))
        classes[cls] = classes.get(cls, 0) + 1
        if cls not in ANCHOR_CLASSES:
            problems.append(f"{aid}: unknown anchor class {cls!r}")
            continue
        grades = k.get("expected_grades")
        if (not isinstance(grades, list) or not grades
                or not set(grades) <= ANCHOR_BANDS[cls]):
            problems.append(f"{aid}: expected_grades {grades!r} outside the pre-registered "
                            f"{cls} band {sorted(ANCHOR_BANDS[cls])}")
        for field in ("rationale", "grounding"):
            if not str(k.get(field, "")).strip():
                problems.append(f"{aid}: key row missing {field}")
    third = want // 3
    for cls in ANCHOR_CLASSES:
        if classes.get(cls, 0) != third:
            problems.append(f"anchor key class {cls}: {classes.get(cls, 0)} rows, expected {third}")
    return problems


def verify_multi_hop_edges(rows: List[Dict[str, Any]], graph: Dict[str, Any]) -> List[str]:
    """Check every declared multi-hop edge exists in the graph verbatim (label + file + relation on
    both endpoints). Graph-dependent — callers gate on :func:`find_graph_json`."""
    nodes = {nd["id"]: nd for nd in graph.get("nodes", [])}
    have = set()
    for link in graph.get("links", []):
        s, t = nodes.get(link.get("source")), nodes.get(link.get("target"))
        if not s or not t:
            continue
        have.add((str(s.get("label", "")), str(s.get("source_file", "")),
                  str(link.get("relation", "")),
                  str(t.get("label", "")), str(t.get("source_file", ""))))
    problems: List[str] = []
    for row in rows:
        if row.get("stratum") != "multi_hop":
            continue
        for e in row.get("edges", []):
            key = (str(e.get("source", "")), str(e.get("source_file", "")),
                   str(e.get("relation", "")), str(e.get("target", "")),
                   str(e.get("target_file", "")))
            if key not in have:
                problems.append(f"{row.get('qid')}: declared edge not in graph: "
                                f"{key[0]} ({key[1]}) -{key[2]}-> {key[3]} ({key[4]})")
    return problems


def validate_all(root: Optional[str] = None) -> List[str]:
    """Every graph-independent check over the committed fixtures — the tests' single entry point."""
    base = root or _root()
    thresholds = load_thresholds(base)
    meta, rows = load_eval_set(base)
    _, anchors = load_anchors(base)
    _, key = load_anchor_key(base)
    problems = validate_eval_set(meta, rows, thresholds, root=base)
    problems += validate_anchors(anchors, key, thresholds, root=base)
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python -m cisco_toolkit.d10_eval_set --verify [--graph PATH]`` validates the committed
    fixtures; where a graph.json is reachable it also verifies the declared multi-hop edges and
    reports (informationally) whether the identifier stratum still reproduces from the CURRENT
    graph — the fixture is frozen at registration, so drift after later commits is EXPECTED and
    reported, never an error. Exit 0 clean, 4 on contract violations (the selfcheck convention)."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    root = _root()
    graph_path = None
    if "--graph" in argv:
        graph_path = argv[argv.index("--graph") + 1]
    problems = validate_all(root)
    _, rows = load_eval_set(root)
    gp = graph_path or find_graph_json(root)
    if gp:
        with open(gp, encoding="utf-8") as f:
            graph = json.load(f)
        problems += verify_multi_hop_edges(rows, graph)
        fresh, prov = extract_identifier_queries(graph)
        committed = [(r["symbol"], r["qrels"][0]["doc"]) for r in rows
                     if r.get("stratum") == "identifier"]
        current = [(r["symbol"], r["qrels"][0]["doc"]) for r in fresh]
        if committed == current:
            print(f"identifier stratum reproduces exactly from {gp} "
                  f"(@ {prov['built_at_commit'][:9]}, {prov['nodes']} nodes)")
        else:
            drift = [f"{a} != {b}" for a, b in zip(committed, current) if a != b]
            print(f"identifier stratum drifted vs CURRENT graph ({len(drift)} positions) — "
                  f"expected after later commits; the fixture stays frozen at registration")
    else:
        print("graph.json not reachable from here (worktree/clean clone) — multi-hop edge check "
              "and identifier reproduction skipped, said so rather than passed silently")
    for p in problems:
        print(f"PROBLEM: {p}")
    print(f"{'OK' if not problems else 'INVALID'}: eval-set fixtures "
          f"({len(rows)} query rows) checked against the P2-0d pre-registration")
    return 0 if not problems else 4


if __name__ == "__main__":
    raise SystemExit(main())
