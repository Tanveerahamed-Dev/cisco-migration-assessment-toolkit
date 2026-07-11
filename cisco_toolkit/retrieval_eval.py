"""D10 Phase-2 retrieval falsification harness (P2-2) — judge gate, configs, pooling, verdicts.

Runs the pre-registered falsification protocol of docs/d10-retrieval-eval-design-2026-07-08.md
(§3 metrics, §4 frozen tuning, §6 judge gate, §7 criteria + the DEC-006 amendment A1–A3) over the
FROZEN P2-1 fixtures (:mod:`cisco_toolkit.d10_eval_set`) and the pre-registered thresholds
(docs/quality/d10-eval-thresholds.json — the decision owner; this module reads every bar and frozen
parameter from it and hardcodes none, Law 1). Nothing here tunes anything: the harness measures,
compares against the committed bars, and reports.

**The two configs** (the §7 headline comparison; one graphify call per query, shared by both):

* **A = graph-only** — the built graph lane (:func:`cisco_toolkit.recall.graph_rank`, offline AST
  subprocess), tokens mapped to corpus doc ids (:func:`map_graph_tokens_to_docs`).
* **B = graph ⊕ BM25** — RRF fusion (:func:`cisco_toolkit.recall.rrf_fuse`, k frozen from the
  thresholds) of the same graph lane with Okapi BM25 (``rank_bm25``, the §4 frozen ``k1``/``b``
  priors) over the eval corpus.

**The corpus** (DEC-006 A1/A2): every git-TRACKED ``*.py`` + ``*.md`` file (a superset of the
fixture ``_meta.corpus_contract.required`` union — the recorded contract lists ``webapp/*.py`` but
its own qrels cite ``webapp/backend/*.py``, so the harness indexes tracked-wide rather than
glob-narrow) ⊕ the provenance-VERIFIED vault digest when one exists locally (entry ids
``digest:<id>``). Digest presence/absence is RECORDED per run and configs are never pooled across
corpus configs — a digest-absent run certifies the degraded graph+docs mode only (A2).

**Judge gate first** (§6): the 15 sealed anchors run through the local-Ollama judge BEFORE any
scoring — dual-prompt (neutral + adversarial), take-the-MIN, two independent passes; the gate
requires self-consistency Cohen's κ ≥ the pre-registered floor AND anchor accuracy ≥ its floor,
scored against the SEALED key (:func:`cisco_toolkit.d10_eval_set.load_anchor_key` — consumed only
by the scorer, never placed in a prompt). Ollama unreachable or gate failed ⇒ the judged strata
(semantic / multi-hop pooling) are INVALID: recorded ``signal_absent``/``failed`` honestly, the
IDENTIFIER stratum still scores (exact labels need no judge), and the overall run is PARTIAL.
Grades are never fabricated.

**Scoring conventions — stated here BEFORE any run** (they are part of the harness contract, not
post-hoc choices): binary metrics (MRR@5, P@1, Recall@10) binarize at grade ≥ 2 and nDCG@5 uses
graded values (both recorded in the fixture ``_meta`` at P2-1 registration); MRR@5/P@1 come from
``pytrec_eval`` (the reference ``trec_eval`` binding, §8) with runs truncated to the cutoff;
Recall@10 is computed directly (|relevant ∩ top-10| / |relevant|). NEGATIVE rows have empty qrels
by construction, so rank metrics are undefined on them — they are excluded from MRR/t-test
aggregates and reported as the over-retrieval diagnostic (§2: docs retrieved for unanswerable
queries; lower is better). ``Hole@k`` = fraction of a query's top-k docs unseen by any annotation
(authored ∪ pooled qrels), meaned over answerable queries — the §3 pool-bias diagnostic, with the
§7 validity bar ``Hole@10`` ≤ its pre-registered maximum. The paired t-test (scipy, pre-registered)
runs on per-query MRR@5 (A vs B) over answerable queries; Cohen's d is the PAIRED dz =
mean(diff)/sd(diff) (the owner's corrected §7 power note is for exactly this statistic).

**Pooling** (§7 "re-pool"): unjudged top-10 docs of the JUDGED strata (semantic, multi-hop) are
graded by the same screened judge and appended — with provenance — to a SEPARATE pooled-qrels file
(docs/quality/d10-pooled-qrels.jsonl). The P2-1 fixtures are SHA-pinned and never edited; authored
grades take precedence over pooled ones on any overlap.

**Fences.** This module stays inside the no-egress attestation (:mod:`cisco_toolkit.attestation`):
no ``socket``/``urllib`` at any depth — ALL Ollama I/O lives in the root-level subprocess helper
``ollama_retrieval_judge.py`` (the ``ollama_recall.py`` idiom), which this module invokes with a
pairs file and reads JSON back from. ``rank_bm25`` / ``pytrec_eval`` / ``scipy`` (the ``[eval]``
extra, P2-0b) are imported lazily so the engine never requires them; the judge helper reuses this
module's PURE prompt/schema/scoring functions so there is one implementation of the gate logic and
the hermetic tests never need a model.

Hard precondition (enforced, not assumed): the P2-1 fixtures must exist and validate cleanly
(:func:`cisco_toolkit.d10_eval_set.validate_all`) or the run REFUSES, citing P2-1 — the harness
never builds or repairs its own eval set.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import subprocess
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from cisco_toolkit.d10_eval_set import (
    EVAL_SET_PATH, load_anchor_key, load_anchors, load_eval_set, load_thresholds)
from cisco_toolkit.recall import QUERY_LOG_PATH, VAULT_DIGEST_DIR, graph_rank, rrf_fuse, tokenize

ANSWERABLE_STRATA = ("identifier", "semantic", "multi_hop")
JUDGED_STRATA = ("semantic", "multi_hop")          # pooling needs the screened judge (§6)
CONFIG_A = "graph"                                  # graph-only (the recall.py graph lane)
CONFIG_B = "graph+bm25"                             # graph ⊕ BM25 fused via RRF (frozen k)
CONFIGS = (CONFIG_A, CONFIG_B)

POOLED_QRELS_PATH = os.path.join("docs", "quality", "d10-pooled-qrels.jsonl")
JUDGE_HELPER = "ollama_retrieval_judge.py"          # repo root — OUTSIDE the no-egress fence
RESULTS_BASENAME = "d10-eval-results-{date}.md"     # docs/quality/, written by --run

MRR_CUTOFF = 5                                      # §3: lock cutoffs at k ≤ 10; primary MRR@5
HOLE_CUTOFF = 10                                    # §7 validity: Hole@10
BINARIZE_FLOOR = 2                                  # fixture _meta: grade>=2 is relevant (frozen)


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- corpus (DEC-006: graph ⊕ docs ⊕ digest-when-present, recorded) -------------------------------

def tracked_files(root: str, suffixes: Tuple[str, ...] = (".py", ".md")) -> List[str]:
    """Git-TRACKED files with the given suffixes — the reproducible corpus universe (scratch and
    gitignored trees stay out by construction). Returns repo-relative POSIX paths (the fixture's
    doc-id convention)."""
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"git ls-files failed under {root!r}: {out.stderr.strip()!r}")
    return [p for p in out.stdout.splitlines() if p and p.endswith(suffixes)]


def digest_lane_status(root: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Load + provenance-verify the local vault digest into ``{'digest:<id>': text}`` AND record
    what was actually measured (DEC-006 A2): per digest file — name, entry count, file SHA-256 and
    the ``verify_feed`` verdict (a refused digest counts as ABSENT and is recorded as refused).
    Parallels :func:`cisco_toolkit.recall.load_vault_digest` deliberately: that loader drops the
    provenance metadata the A2 recording contract requires, so the eval uses this recording
    variant. No digest at all -> ``({}, {"present": False, ...})`` — the degraded graph+docs mode,
    said so, never silently mixed."""
    import glob as _glob
    import hashlib
    from cisco_toolkit.intel_feed import verify_feed
    corpus: Dict[str, str] = {}
    files: List[Dict[str, Any]] = []
    for p in sorted(_glob.glob(os.path.join(root, VAULT_DIGEST_DIR, "digest-*.jsonl"))):
        rec: Dict[str, Any] = {"file": os.path.basename(p)}
        try:
            raw = open(p, encoding="utf-8").read()
        except OSError as ex:
            rec.update({"verdict": f"unreadable: {ex}", "entries": 0})
            files.append(rec)
            continue
        rec["file_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        res = verify_feed(raw)
        if not res.get("ok"):
            rec.update({"verdict": f"REFUSED: {res.get('reason', 'verify_feed not ok')}",
                        "entries": 0})
            files.append(rec)
            continue
        entries = res.get("entries", [])
        rec.update({"verdict": "verify_feed OK", "entries": len(entries)})
        files.append(rec)
        for e in entries:
            corpus[f"digest:{e.get('id')}"] = " ".join(
                str(e.get(f, "")) for f in ("title", "detail", "notes", "tags"))
    status = {"present": bool(corpus), "files": files, "entry_count": len(corpus)}
    return corpus, status


def build_eval_corpus(root: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """The eval corpus ``{doc_id: text}`` per the fixture corpus contract (see module docstring)
    plus the environment record. File doc text is ``<relpath>\\n<content>`` so the path itself is
    a first-class lexical signal (identifier queries name files; both lanes see the same text)."""
    corpus: Dict[str, str] = {}
    for rel in tracked_files(root):
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
                corpus[rel.replace("\\", "/")] = rel + "\n" + f.read()
        except OSError:
            continue
    digest_corpus, digest_status = digest_lane_status(root)
    corpus.update(digest_corpus)
    env = {"tracked_docs": len(corpus) - len(digest_corpus), "digest": digest_status}
    return corpus, env


# --- the two lanes ---------------------------------------------------------------------------------

def map_graph_tokens_to_docs(tokens: Sequence[str], corpus_ids: Sequence[str]) -> List[str]:
    """Map :func:`graph_rank` output tokens onto corpus doc ids, first-seen order, deterministic:
    normalize ``\\``→``/`` and strip a trailing ``:line``; keep an exact corpus match, else a
    UNIQUE-suffix match (graphify may print paths relative to a subdir); drop everything else
    (bare ``symbol()`` tokens have no doc identity — mapping them would fabricate a hit)."""
    ids = list(corpus_ids)
    id_set = set(ids)
    out: List[str] = []
    for tok in tokens:
        t = str(tok).replace("\\", "/")
        if ":" in t:
            base, _, tail = t.rpartition(":")
            if tail.isdigit():
                t = base
        if not t.endswith((".py", ".md")):
            continue
        if t in id_set:
            hit: Optional[str] = t
        else:
            suffix = [d for d in ids if d.endswith("/" + t)]
            hit = suffix[0] if len(suffix) == 1 else None
        if hit and hit not in out:
            out.append(hit)
    return out


class Bm25Lane:
    """Okapi BM25 over the eval corpus with the §4 FROZEN priors (read from the thresholds file,
    never hardcoded). Lazy ``rank_bm25`` import — the [eval] extra (P2-0b)."""

    def __init__(self, corpus: Dict[str, str], *, k1: float, b: float) -> None:
        from rank_bm25 import BM25Okapi
        self.ids = sorted(corpus)                    # deterministic doc order
        self._bm = BM25Okapi([tokenize(corpus[d]) for d in self.ids], k1=k1, b=b)

    def rank(self, query: str, *, limit: int = 50) -> List[str]:
        scores = self._bm.get_scores(tokenize(query))
        scored = [(s, d) for s, d in zip(scores, self.ids) if s > 0]
        scored.sort(key=lambda sd: (-sd[0], sd[1]))
        return [d for _, d in scored[:limit]]


def run_configs(rows: List[Dict[str, Any]], corpus: Dict[str, str], thresholds: Dict[str, Any],
                *, graph_ranker: Optional[Callable[[str], List[str]]] = None,
                top_k: int = HOLE_CUTOFF) -> Dict[str, Dict[str, List[str]]]:
    """Produce ``{config: {qid: top-k doc ids}}`` for the two §7 configs. ONE graph call per query
    (injectable for hermetic tests), shared verbatim by A and B so the comparison isolates the BM25
    lane. RRF k and BM25 priors come from the pre-registered ``tuning_frozen`` block."""
    frozen = thresholds.get("tuning_frozen", {})
    rrf_k = int(frozen.get("rrf_k", 60))
    lane = Bm25Lane(corpus, k1=float(frozen.get("bm25_k1", 0.9)), b=float(frozen.get("bm25_b", 0.4)))
    granker = graph_ranker if graph_ranker is not None else graph_rank
    ids = list(corpus)
    runs: Dict[str, Dict[str, List[str]]] = {c: {} for c in CONFIGS}
    for row in rows:
        qid, query = str(row["qid"]), str(row["query"])
        graph_docs = map_graph_tokens_to_docs(granker(query), ids)
        bm25_docs = lane.rank(query)
        runs[CONFIG_A][qid] = graph_docs[:top_k]
        fused = [d for d, _ in rrf_fuse([graph_docs, bm25_docs], k=rrf_k)]
        runs[CONFIG_B][qid] = fused[:top_k]
    return runs


# --- qrels + metrics -------------------------------------------------------------------------------

def authored_qrels(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    return {str(r["qid"]): {str(q["doc"]): int(q["grade"]) for q in r.get("qrels", [])}
            for r in rows}


def load_pooled_qrels(path: str) -> Dict[str, Dict[str, int]]:
    """The SEPARATE pool-judgment file (append-only; the frozen fixtures are never edited)."""
    out: Dict[str, Dict[str, int]] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "_meta" in row:
                continue
            out.setdefault(str(row["qid"]), {})[str(row["doc"])] = int(row["grade"])
    return out


def merge_qrels(authored: Dict[str, Dict[str, int]],
                pooled: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """Authored grades win on overlap (the frozen fixture is the registered annotation; a pooled
    judge grade never overrides it)."""
    merged = {qid: dict(docs) for qid, docs in pooled.items()}
    for qid, docs in authored.items():
        merged.setdefault(qid, {}).update(docs)
    return merged


def binarize(qrels: Dict[str, Dict[str, int]], floor: int = BINARIZE_FLOOR) -> Dict[str, Dict[str, int]]:
    return {qid: {d: (1 if g >= floor else 0) for d, g in docs.items()}
            for qid, docs in qrels.items()}


def _run_scores(ranked: Sequence[str], cutoff: Optional[int] = None) -> Dict[str, float]:
    docs = list(ranked)[: cutoff or len(ranked)]
    return {d: float(len(docs) - i) for i, d in enumerate(docs)}


def score_config(run: Dict[str, List[str]], graded: Dict[str, Dict[str, int]],
                 qids: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """Per-query metrics for one config over ``qids`` (answerable only): MRR@5 + P@1 via
    ``pytrec_eval`` on the grade≥2 binarization (runs truncated to the MRR cutoff), nDCG@5 on the
    graded qrels, Recall@10 computed directly. Returns ``{qid: {metric: value}}``."""
    import pytrec_eval
    binary = binarize({q: graded.get(q, {}) for q in qids})
    graded_sub = {q: {d: g for d, g in graded.get(q, {}).items()} for q in qids}
    run_cut = {q: _run_scores(run.get(q, []), MRR_CUTOFF) for q in qids}
    run_full = {q: _run_scores(run.get(q, [])) for q in qids}
    ev_bin = pytrec_eval.RelevanceEvaluator(binary, {"recip_rank", "P_1"})
    ev_gra = pytrec_eval.RelevanceEvaluator(graded_sub, {"ndcg_cut_5"})
    res_bin = ev_bin.evaluate(run_cut)
    res_gra = ev_gra.evaluate(run_full)
    out: Dict[str, Dict[str, float]] = {}
    for q in qids:
        rel = {d for d, g in binary.get(q, {}).items() if g > 0}
        top10 = list(run.get(q, []))[:HOLE_CUTOFF]
        recall10 = (len(rel & set(top10)) / len(rel)) if rel else 0.0
        out[q] = {"mrr@5": float(res_bin.get(q, {}).get("recip_rank", 0.0)),
                  "p@1": float(res_bin.get(q, {}).get("P_1", 0.0)),
                  "ndcg@5": float(res_gra.get(q, {}).get("ndcg_cut_5", 0.0)),
                  "recall@10": recall10}
    return out


def hole_at_k(run: Dict[str, List[str]], judged: Dict[str, Dict[str, int]],
              qids: Sequence[str], k: int = HOLE_CUTOFF) -> float:
    """§3 pool-bias diagnostic: mean fraction of a query's top-k docs carrying NO annotation
    (authored ∪ pooled). Empty retrievals contribute 0 (abstention is not a hole)."""
    fracs: List[float] = []
    for q in qids:
        top = list(run.get(q, []))[:k]
        if not top:
            fracs.append(0.0)
            continue
        seen = set(judged.get(q, {}))
        fracs.append(sum(1 for d in top if d not in seen) / len(top))
    return sum(fracs) / len(fracs) if fracs else 0.0


def negative_diagnostic(run: Dict[str, List[str]], negative_qids: Sequence[str],
                        k: int = MRR_CUTOFF) -> Dict[str, float]:
    """Over-retrieval on unanswerable queries (§2): mean docs returned in top-k and the fraction of
    negative queries retrieving ANYTHING — lower is better on both. A diagnostic, never part of the
    MRR aggregate (empty qrels make rank metrics undefined — stated in the module contract)."""
    if not negative_qids:
        return {"mean_returned@5": 0.0, "any_returned_rate": 0.0}
    counts = [len(list(run.get(q, []))[:k]) for q in negative_qids]
    return {"mean_returned@5": sum(counts) / len(counts),
            "any_returned_rate": sum(1 for c in counts if c) / len(counts)}


def paired_stats(per_q_a: Dict[str, Dict[str, float]], per_q_b: Dict[str, Dict[str, float]],
                 qids: Sequence[str], metric: str = "mrr@5") -> Dict[str, Any]:
    """The pre-registered decision statistics on per-query pairs: scipy paired t-test + PAIRED
    Cohen's dz = mean(diff)/sd(diff, ddof=1). Zero-variance diffs are degenerate for a t-test —
    recorded honestly (p=None) instead of a fabricated significance."""
    a = [float(per_q_a.get(q, {}).get(metric, 0.0)) for q in qids]
    b = [float(per_q_b.get(q, {}).get(metric, 0.0)) for q in qids]
    n = len(qids)
    diffs = [y - x for x, y in zip(a, b)]
    mean_d = sum(diffs) / n if n else 0.0
    out: Dict[str, Any] = {"n": n, "metric": metric,
                           "mean_a": sum(a) / n if n else 0.0,
                           "mean_b": sum(b) / n if n else 0.0,
                           "delta": mean_d}
    var = sum((d - mean_d) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    if n < 2 or sd == 0.0:
        out.update({"p_value": None, "cohens_dz": 0.0 if mean_d == 0.0 else None,
                    "note": "degenerate: fewer than 2 pairs or zero-variance diffs — "
                            "no significance claim"})
        return out
    from scipy import stats
    t = stats.ttest_rel(b, a)
    out.update({"p_value": float(t.pvalue), "cohens_dz": mean_d / sd})
    return out


def bm25_verdict(stats: Dict[str, Any], thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """§7 'BM25 earns its place', decided ONLY against the pre-registered bars: margin from
    ``criteria.bm25_earns_place``, significance from ``significance`` (p AND dz BOTH clear)."""
    crit = thresholds["criteria"]["bm25_earns_place"]
    sig = thresholds["significance"]
    margin = float(crit["margin"])
    p, dz = stats.get("p_value"), stats.get("cohens_dz")
    margin_ok = stats["mean_b"] > stats["mean_a"] + margin
    sig_ok = (p is not None and dz is not None
              and p < float(sig["p_max"]) and dz > float(sig["cohens_d_min"]))
    verdict = "EARNED" if (margin_ok and sig_ok) else str(crit["on_fail"])
    return {"criterion": f"MRR@5({CONFIG_B}) > MRR@5({CONFIG_A}) + {margin}, "
                         f"p < {sig['p_max']} paired-t AND dz > {sig['cohens_d_min']}",
            "margin_cleared": margin_ok, "significant": sig_ok, "verdict": verdict}


def dense_column_status(root: str, thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """The §5 dense-lane precondition, read from the REAL query log (in-code owner:
    :data:`cisco_toolkit.recall.QUERY_LOG_PATH`) — never sampled from memory, never guessed. Below
    the pre-registered row floor the dense column is DEFERRED, stated as such."""
    pre = thresholds.get("dense_precondition", {})
    need = int(pre.get("n_real_queries", 30))
    path = os.path.join(root, QUERY_LOG_PATH)
    n = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
    status = "DEFERRED" if n < need else "PRECONDITION MET — classify the mix before adding dense"
    return {"status": status, "real_queries_logged": n, "required": need,
            "semantic_share_min": pre.get("semantic_share_min"),
            "note": "the traffic mix is measured, not assumed (owner §5); no dense config runs "
                    "until the log clears the floor and classifies ≥ the semantic share"}


# --- judge gate (§6) — pure logic here, ALL Ollama I/O in the root helper --------------------------

GRADING_GRADES = (0, 1, 2, 3)


def judge_schema() -> Dict[str, Any]:
    """Ollama structured-output schema for one (query, doc) grade: reasoning FIRST, then the 0–3
    grade as an enum (the :mod:`ollama_judge` idiom — reason before committing, always parseable).

    ``maxLength`` on the reasoning is GRAMMAR-ENFORCED (llama.cpp json-schema-to-grammar): it
    forces the string to close so the grade token is always reached. Without it, qwen3:4b
    deliberated unboundedly on one anchor's content until the token budget died mid-string
    (unterminated JSON → an honest None → gate unable to measure κ at all) — a prompt-level word
    bound and repeat_penalty both failed to stop it; the grammar bound is structural. Applied
    uniformly to every pair and both prompt arms; chosen for JSON validity, never grade shaping."""
    return {"type": "object",
            "properties": {"reasoning": {"type": "string", "maxLength": 400},
                           "grade": {"type": "integer", "enum": list(GRADING_GRADES)}},
            "required": ["reasoning", "grade"]}


def judge_prompts(query: str, doc_id: str, excerpt: str,
                  rubric: Dict[str, str]) -> Dict[str, str]:
    """The §6 dual prompts — one NEUTRAL, one ADVERSARIAL ('find why it does NOT answer') — whose
    grades are combined take-the-MIN (:func:`combine_dual`), the conservative ensemble against
    rubber-stamping. The rubric text comes from the fixture ``_meta`` (frozen at P2-1)."""
    scale = "\n".join(f"- {g}: {rubric.get(str(g), '')}" for g in GRADING_GRADES)
    # The 60-word bound is OUTPUT-BUDGET engineering, not debiasing: an unbounded reasoning field
    # overran the token budget mid-string on the adversarial arm (unterminated JSON -> an honest
    # None grade), measured on a SYNTHETIC probe before any sealed anchor was ever graded.
    head = (f"QUERY: {query}\n\nDOCUMENT (id: {doc_id}) EXCERPT:\n{excerpt}\n\n"
            f"Grading scale:\n{scale}\n"
            "Keep the reasoning to AT MOST 60 words, then commit to one integer grade.\n")
    neutral = (
        "You are grading search-result relevance for a network-engineering codebase.\n"
        "Read the query and the document excerpt, reason briefly about what the query needs and\n"
        "what the document actually contains, then give ONE integer grade on the scale.\n\n" + head)
    adversarial = (
        "You are a skeptical reviewer. Your job is to find why this document does NOT answer the\n"
        "query: look for topic overlap that is merely superficial, terms used in a different\n"
        "sense, or content that mentions the subject without addressing the question. Reason\n"
        "through the strongest case AGAINST relevance first (briefly), then grade only what\n"
        "survives that case, on the scale.\n\n" + head)
    return {"neutral": neutral, "adversarial": adversarial}


def combine_dual(neutral_grade: int, adversarial_grade: int) -> int:
    """Take-the-MIN (§6): the conservative member of the dual-prompt ensemble decides."""
    return min(int(neutral_grade), int(adversarial_grade))


def excerpt_for_judge(query: str, text: str, *, size: int = 1800) -> str:
    """Deterministic excerpt: the window (of ``size`` chars, half-overlapping steps) with the most
    query-token occurrences — earliest window on ties, so the judge sees the doc's most
    query-relevant region rather than a blind head. Whole doc when it already fits."""
    if len(text) <= size:
        return text
    qtoks = set(tokenize(query))
    step = max(1, size // 2)
    best_start, best_hits = 0, -1
    for start in range(0, len(text) - size + step, step):
        window = text[start:start + size].lower()
        hits = sum(window.count(t) for t in qtoks)
        if hits > best_hits:
            best_start, best_hits = start, hits
    return text[best_start:best_start + size]


def cohens_kappa(a: Sequence[int], b: Sequence[int],
                 labels: Sequence[int] = GRADING_GRADES) -> float:
    """Unweighted Cohen's κ between two grade sequences (the §6 self-consistency statistic).
    Degenerate agreement (both raters constant and equal) is perfect consistency → 1.0; constant
    disagreement → 0.0 via the standard formula guard."""
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal-length, non-empty grade sequences")
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((list(a).count(l) / n) * (list(b).count(l) / n) for l in labels)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def screen_judge(pass1_final: Dict[str, int], pass2_final: Dict[str, int],
                 key_rows: List[Dict[str, Any]], thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """Score the anchor gate against the SEALED key (§6; the key is consumed here — the scorer —
    and nowhere near a prompt): self-consistency κ between the two passes' final (post-MIN) grades,
    accuracy = pass-1 final grade inside the key's pre-registered band, both floors from the
    pre-registered ``validity_gate``. Missing anchors fail loudly (a partial gate proves nothing)."""
    gate = thresholds["validity_gate"]
    aids = sorted(str(k["aid"]) for k in key_rows)
    missing = [a for a in aids if a not in pass1_final or a not in pass2_final]
    if missing:
        return {"status": "failed", "reason": f"anchors ungraded: {missing}",
                "kappa": None, "accuracy": None}
    g1 = [int(pass1_final[a]) for a in aids]
    g2 = [int(pass2_final[a]) for a in aids]
    kappa = cohens_kappa(g1, g2)
    key_by_aid = {str(k["aid"]): k for k in key_rows}
    hits = sum(1 for a in aids if int(pass1_final[a]) in set(key_by_aid[a]["expected_grades"]))
    accuracy = hits / len(aids)
    passed = kappa >= float(gate["judge_kappa_min"]) and accuracy >= float(gate["anchor_accuracy_min"])
    return {"status": "passed" if passed else "failed",
            "kappa": round(kappa, 4), "accuracy": round(accuracy, 4),
            "floors": {"kappa": gate["judge_kappa_min"], "accuracy": gate["anchor_accuracy_min"]},
            "per_anchor": {a: {"pass1": pass1_final[a], "pass2": pass2_final[a],
                               "band": sorted(key_by_aid[a]["expected_grades"])} for a in aids}}


def invoke_judge_helper(pairs: List[Dict[str, Any]], *, root: str, passes: int = 1,
                        timeout: int = 5400) -> Dict[str, Any]:
    """Run the root-level Ollama helper as a SUBPROCESS over ``pairs`` (each: pid/query/doc/
    excerpt/rubric) and parse its one-line JSON result. Ollama down / helper missing / bad JSON →
    ``{"ok": False, "reason": …}`` — signal_absent honesty, never a fabricated grade."""
    helper = os.path.join(root, JUDGE_HELPER)
    if not os.path.exists(helper):
        return {"ok": False, "reason": f"judge helper missing: {helper}"}
    payload = json.dumps({"pairs": pairs, "passes": passes})
    tmp = os.path.join(root, "docs", "quality", ".d10-judge-pairs.tmp.json")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        out = subprocess.run(["python", helper, "--pairs", tmp], cwd=root,
                             capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return {"ok": False, "reason": f"helper exit {out.returncode}: {out.stderr.strip()[:400]}"}
        return json.loads(out.stdout.strip() or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as ex:
        return {"ok": False, "reason": f"helper invocation failed: {ex}"}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def run_judge_gate(root: str, thresholds: Dict[str, Any], rubric: Dict[str, str],
                   corpus: Dict[str, str], *,
                   invoke: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """§6, FIRST every session: grade the 15 judge-visible anchors (dual-prompt, take-the-MIN,
    TWO independent passes) and screen against the sealed key. The anchor payload carries ONLY
    aid/query/doc/excerpt — the key never leaves the scorer."""
    _, anchors = load_anchors(root)
    _, key = load_anchor_key(root)
    pairs = []
    for a in anchors:
        doc = str(a["doc"])
        text = corpus.get(doc)
        if text is None:
            try:
                with open(os.path.join(root, doc), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                text = ""
        pairs.append({"pid": str(a["aid"]), "query": str(a["query"]), "doc": doc,
                      "excerpt": excerpt_for_judge(str(a["query"]), text), "rubric": rubric})
    do = invoke if invoke is not None else invoke_judge_helper
    res = do(pairs, root=root, passes=2)
    if not res.get("ok"):
        return {"status": "signal_absent", "reason": str(res.get("reason", "judge unavailable")),
                "kappa": None, "accuracy": None, "model": res.get("model")}
    finals: List[Dict[str, int]] = [{}, {}]
    for g in res.get("grades", []):
        by_pass = g.get("final_by_pass", [])
        for i in (0, 1):
            if i < len(by_pass) and by_pass[i] is not None:
                finals[i][str(g.get("pid"))] = int(by_pass[i])
    gate = screen_judge(finals[0], finals[1], key, thresholds)
    gate["model"] = res.get("model")
    return gate


# --- pooling (§7 re-pool: judge the unjudged, append to the SEPARATE file) --------------------------

def pool_unjudged(runs: Dict[str, Dict[str, List[str]]], judged: Dict[str, Dict[str, int]],
                  rows: List[Dict[str, Any]], k: int = HOLE_CUTOFF) -> List[Tuple[str, str]]:
    """Union of both configs' top-k docs on the JUDGED strata that carry no annotation yet —
    the §3/§7 pool, sorted for determinism."""
    strata = {str(r["qid"]): str(r["stratum"]) for r in rows}
    pool: set = set()
    for run in runs.values():
        for qid, docs in run.items():
            if strata.get(qid) not in JUDGED_STRATA:
                continue
            seen = set(judged.get(qid, {}))
            pool.update((qid, d) for d in list(docs)[:k] if d not in seen)
    return sorted(pool)


def judge_pool(pool: List[Tuple[str, str]], rows: List[Dict[str, Any]], corpus: Dict[str, str],
               rubric: Dict[str, str], *, root: str,
               invoke: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Grade the pooled (qid, doc) pairs with the SCREENED judge (single pass, dual-prompt MIN).
    Returns ``{ok, grades: {(qid, doc): grade}, model}`` — or signal_absent honesty."""
    queries = {str(r["qid"]): str(r["query"]) for r in rows}
    pairs = []
    for qid, doc in pool:
        text = corpus.get(doc, "")
        pairs.append({"pid": f"{qid}|{doc}", "query": queries.get(qid, ""), "doc": doc,
                      "excerpt": excerpt_for_judge(queries.get(qid, ""), text), "rubric": rubric})
    do = invoke if invoke is not None else invoke_judge_helper
    res = do(pairs, root=root, passes=1)
    if not res.get("ok"):
        return {"ok": False, "reason": str(res.get("reason", "judge unavailable"))}
    grades: Dict[Tuple[str, str], int] = {}
    for g in res.get("grades", []):
        pid = str(g.get("pid", ""))
        if "|" not in pid:
            continue
        qid, doc = pid.split("|", 1)
        fb = g.get("final_by_pass", [])
        if fb and fb[0] is not None:
            grades[(qid, doc)] = int(fb[0])
    return {"ok": True, "grades": grades, "model": res.get("model")}


def append_pooled_qrels(grades: Dict[Tuple[str, str], int], *, root: str, model: str,
                        date: str, path: str = POOLED_QRELS_PATH) -> int:
    """Append pool judgments — with provenance — to the SEPARATE pooled-qrels file. Never touches
    the frozen fixtures. Returns rows written."""
    p = os.path.join(root, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    existing = load_pooled_qrels(p)
    n = 0
    with open(p, "a", encoding="utf-8") as f:
        for (qid, doc), grade in sorted(grades.items()):
            if doc in existing.get(qid, {}):
                continue
            f.write(json.dumps({"qid": qid, "doc": doc, "grade": int(grade),
                                "judge": model, "date": date,
                                "source": "P2-2 pool judging (screened judge; dual-prompt MIN)"},
                               ensure_ascii=False) + "\n")
            n += 1
    return n


# --- environment + orchestration -------------------------------------------------------------------

def environment_report(root: str, corpus_env: Dict[str, Any]) -> Dict[str, Any]:
    """The DEC-006 A2 record of what was actually measured: digest lane, Ollama version (read LIVE
    per the P2-0c disposition — never cached), judge model default, query-log row count."""
    try:
        out = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=15)
        ollama_version = out.stdout.strip() or out.stderr.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        ollama_version = "not on PATH"
    return {"digest": corpus_env.get("digest"),
            "tracked_docs": corpus_env.get("tracked_docs"),
            "ollama_version": ollama_version,
            "judge_model_env": os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3:4b (in-code default)")}


def run_eval(root: Optional[str] = None, *, out_dir: Optional[str] = None,
             graph_ranker: Optional[Callable[[str], List[str]]] = None,
             judge_invoke: Optional[Callable[..., Dict[str, Any]]] = None,
             today: Optional[str] = None) -> Dict[str, Any]:
    """The full P2-2 protocol in order: precondition (P2-1 fixtures validate — else REFUSE), judge
    gate FIRST, configs, pooling (judged strata, screened judge only), scoring, pre-registered
    stats + verdicts, honest PARTIAL/INVALID marking. Injectables (``graph_ranker``,
    ``judge_invoke``) exist for hermetic tests; production callers pass none."""
    root = root or _root()
    from cisco_toolkit.d10_eval_set import validate_all
    if not os.path.exists(os.path.join(root, EVAL_SET_PATH)):
        raise RuntimeError("P2-1 fixtures absent (docs/quality/d10-eval-set.jsonl) — the P2-2 run "
                           "REFUSES; merge the P2-1 eval set first, never build a substitute set")
    problems = validate_all(root)
    if problems:
        raise RuntimeError("P2-1 fixture contract INVALID — refusing to run on a corrupt set:\n"
                           + "\n".join(problems))
    thresholds = load_thresholds(root)
    meta, rows = load_eval_set(root)
    rubric = {str(k): str(v) for k, v in (meta.get("grading_rubric") or {}).items()}
    corpus, corpus_env = build_eval_corpus(root)
    env = environment_report(root, corpus_env)
    date = today or datetime.date.today().isoformat()

    # §6 gate FIRST — before any retrieval scoring.
    gate = run_judge_gate(root, thresholds, rubric, corpus, invoke=judge_invoke)
    judge_valid = gate.get("status") == "passed"

    runs = run_configs(rows, corpus, thresholds, graph_ranker=graph_ranker)

    authored = authored_qrels(rows)
    pooled_path = os.path.join(root, POOLED_QRELS_PATH)
    pool_appended = 0
    if judge_valid:
        judged_now = merge_qrels(authored, load_pooled_qrels(pooled_path))
        pool = pool_unjudged(runs, judged_now, rows)
        if pool:
            pj = judge_pool(pool, rows, corpus, rubric, root=root, invoke=judge_invoke)
            if pj.get("ok"):
                pool_appended = append_pooled_qrels(
                    pj["grades"], root=root, model=str(pj.get("model")), date=date)
            else:
                judge_valid = False
                gate = dict(gate, status="failed",
                            reason=f"pool judging lost the judge mid-run: {pj.get('reason')}")
    merged = merge_qrels(authored, load_pooled_qrels(pooled_path))

    strata_of = {str(r["qid"]): str(r["stratum"]) for r in rows}
    scoreable_strata = list(ANSWERABLE_STRATA) if judge_valid else ["identifier"]
    qids_scoreable = [q for q, s in strata_of.items() if s in scoreable_strata]
    negatives = [q for q, s in strata_of.items() if s == "negative"]

    per_q = {c: score_config(runs[c], merged, qids_scoreable) for c in CONFIGS}

    def _mean(cfg: str, qs: List[str], metric: str) -> Optional[float]:
        return (sum(per_q[cfg][q][metric] for q in qs) / len(qs)) if qs else None

    table: Dict[str, Any] = {}
    for stratum in ANSWERABLE_STRATA:
        qs = [q for q in qids_scoreable if strata_of[q] == stratum]
        if stratum in JUDGED_STRATA and not judge_valid:
            table[stratum] = {"status": f"INVALID — judged stratum, judge gate "
                                        f"{gate.get('status')} ({gate.get('reason', 'below floor')})"}
            continue
        table[stratum] = {
            "n": len(qs),
            "stats": paired_stats(per_q[CONFIG_A], per_q[CONFIG_B], qs),
            **{c: {m: _mean(c, qs, m) for m in ("mrr@5", "p@1", "ndcg@5", "recall@10")}
               for c in CONFIGS}}
    table["negative"] = {c: negative_diagnostic(runs[c], negatives) for c in CONFIGS}

    overall = (paired_stats(per_q[CONFIG_A], per_q[CONFIG_B], qids_scoreable)
               if judge_valid else None)
    holes = {c: hole_at_k(runs[c], merged, qids_scoreable) for c in CONFIGS}
    hole_max = float(thresholds["validity_gate"]["hole_at_10_max"])
    holes_ok = all(h <= hole_max for h in holes.values())

    run_status = "COMPLETE" if judge_valid else "PARTIAL"
    if judge_valid and not holes_ok:
        run_status = "INVALID"                     # §7: Hole@10 over the bar -> re-pool, don't report
    results: Dict[str, Any] = {
        "run_status": run_status, "date": date, "environment": env,
        "judge_gate": gate, "pooled_rows_appended": pool_appended,
        "hole@10": {**{c: round(holes[c], 4) for c in CONFIGS},
                    "max_allowed": hole_max, "valid": holes_ok},
        "strata": table, "overall": overall,
        "verdicts": {"bm25_earns_place": (bm25_verdict(overall, thresholds)
                                          if judge_valid and holes_ok and overall else
                                          {"verdict": "UNDECIDED",
                                           "reason": f"run {run_status} — the pre-registered "
                                                     f"criterion needs a valid full run"}),
                     "dense_column": dense_column_status(root, thresholds)},
        "per_stratum_power_note": "owner §7 (corrected): ≈97% overall at dz=0.5 (n=60 frame), but "
                                  "only ≈55%/≈33% per-stratum at n=20/10 — per-stratum deltas are "
                                  "reported, never over-claimed",
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"d10-eval-results-{date}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        with open(os.path.join(out_dir, RESULTS_BASENAME.format(date=date)), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(render_markdown(results))
    return results


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def render_markdown(results: Dict[str, Any]) -> str:
    """The results record (docs/quality/d10-eval-results-<date>.md): environment per DEC-006 A2,
    gate outcome, the 2-config × 4-strata table, pre-registered stats + verdicts. Coverage-honest:
    PARTIAL/INVALID states render as themselves."""
    env = results.get("environment", {})
    gate = results.get("judge_gate", {})
    dig = (env.get("digest") or {})
    lines = [
        f"# D10 Phase-2 retrieval eval — {results.get('date')} ({results.get('run_status')})",
        "",
        "Owner protocol: docs/d10-retrieval-eval-design-2026-07-08.md (§3/§4/§6/§7 + DEC-006 "
        "amendment). Thresholds: docs/quality/d10-eval-thresholds.json (pre-registered — read, "
        "never adjusted). Fixtures: the frozen P2-1 set (SHA-pinned).",
        "",
        "## Environment (recorded per DEC-006 A2)",
        f"- corpus: {env.get('tracked_docs')} tracked docs (git-tracked *.py + *.md) "
        f"⊕ digest {'PRESENT' if dig.get('present') else 'ABSENT'}"
        + (f" ({dig.get('entry_count')} entries: "
           + "; ".join(f"{r.get('file')} sha256={str(r.get('file_sha256'))[:12]}… "
                       f"{r.get('verdict')}" for r in dig.get('files', []))
           + ")" if dig.get("present") else
           " — this run certifies the DEGRADED graph+docs mode only (A2); never pool with "
           "digest-present runs"),
        f"- Ollama: {env.get('ollama_version')} (read live); judge model: "
        f"{env.get('judge_model_env')}",
        "",
        "## Judge screening gate (§6 — run FIRST)",
        f"- status: **{gate.get('status')}**"
        + (f" — {gate.get('reason')}" if gate.get("reason") else ""),
        f"- self-consistency κ: {_fmt(gate.get('kappa'))} · anchor accuracy: "
        f"{_fmt(gate.get('accuracy'))} (floors: κ ≥ "
        f"{(gate.get('floors') or {}).get('kappa', '—')}, acc ≥ "
        f"{(gate.get('floors') or {}).get('accuracy', '—')}) · model: {gate.get('model') or '—'}",
        "",
        "## Results (2 configs × 4 strata + overall)",
        "",
        "| stratum | n | config | MRR@5 | P@1 | nDCG@5 | Recall@10 | Δ MRR@5 (B−A) | p (paired t) | Cohen's dz |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    strata = results.get("strata", {})
    for stratum in ANSWERABLE_STRATA:
        s = strata.get(stratum, {})
        if "status" in s:
            lines.append(f"| {stratum} | — | — | {s['status']} | | | | | | |")
            continue
        st = s.get("stats", {})
        for cfg in CONFIGS:
            m = s.get(cfg, {})
            tail = (f"{_fmt(st.get('delta'))} | {_fmt(st.get('p_value'))} | "
                    f"{_fmt(st.get('cohens_dz'))}" if cfg == CONFIG_B else " | | ")
            lines.append(f"| {stratum} | {s.get('n')} | {cfg} | {_fmt(m.get('mrr@5'))} | "
                         f"{_fmt(m.get('p@1'))} | {_fmt(m.get('ndcg@5'))} | "
                         f"{_fmt(m.get('recall@10'))} | {tail} |")
    neg = strata.get("negative", {})
    for cfg in CONFIGS:
        d = neg.get(cfg, {})
        lines.append(f"| negative (diagnostic) | 10 | {cfg} | over-retrieval: "
                     f"mean {_fmt(d.get('mean_returned@5'))} docs@5, any-returned "
                     f"{_fmt(d.get('any_returned_rate'))} | | | | | | |")
    overall = results.get("overall")
    if overall:
        lines += ["",
                  f"**Overall (answerable n={overall.get('n')}):** MRR@5 {CONFIG_A} "
                  f"{_fmt(overall.get('mean_a'))} vs {CONFIG_B} {_fmt(overall.get('mean_b'))} · "
                  f"Δ {_fmt(overall.get('delta'))} · p {_fmt(overall.get('p_value'))} · "
                  f"dz {_fmt(overall.get('cohens_dz'))}"]
    hole = results.get("hole@10", {})
    lines += ["",
              "**Hole@10 validity:** " + ", ".join(f"{c}: {_fmt(hole.get(c))}" for c in CONFIGS)
              + f" (bar ≤ {hole.get('max_allowed')}) → "
              + ("VALID" if hole.get("valid") else "INVALID — re-pool per §7"),
              "", "## Pre-registered verdicts (§7 — bars read from the thresholds file)", ""]
    v = results.get("verdicts", {})
    bm = v.get("bm25_earns_place", {})
    lines.append(f"- **BM25 earns its place:** **{bm.get('verdict')}**"
                 + (f" — {bm.get('criterion')} (margin cleared: {bm.get('margin_cleared')}, "
                    f"significant: {bm.get('significant')})" if "criterion" in bm else
                    f" — {bm.get('reason', '')}"))
    dc = v.get("dense_column", {})
    lines.append(f"- **Dense column:** **{dc.get('status')}** — "
                 f"{dc.get('real_queries_logged')}/{dc.get('required')} real queries logged; "
                 f"{dc.get('note')}")
    lines += ["", f"- Pooled qrels appended this run: {results.get('pooled_rows_appended')}",
              f"- {results.get('per_stratum_power_note')}", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python -m cisco_toolkit.retrieval_eval --check`` (preconditions + environment, no
    model, no scoring) · ``--gate`` (judge screening gate only) · ``--run`` (the full protocol;
    writes docs/quality/d10-eval-results-<date>.md + .json). Exit 0 on an honest run (PARTIAL
    included — honesty is not an error), 2 on usage, 4 on refused preconditions."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    root = _root()
    if "--check" in argv:
        from cisco_toolkit.d10_eval_set import validate_all
        problems = validate_all(root) if os.path.exists(os.path.join(root, EVAL_SET_PATH)) else \
            ["P2-1 fixtures absent — merge the P2-1 eval set first"]
        corpus, corpus_env = build_eval_corpus(root)
        env = environment_report(root, corpus_env)
        print(json.dumps({"fixtures_ok": not problems, "problems": problems,
                          "corpus_docs": len(corpus), "environment": env}, indent=2))
        return 0 if not problems else 4
    if "--gate" in argv:
        thresholds = load_thresholds(root)
        meta, _rows = load_eval_set(root)
        corpus, _ = build_eval_corpus(root)
        rubric = {str(k): str(v) for k, v in (meta.get("grading_rubric") or {}).items()}
        gate = run_judge_gate(root, thresholds, rubric, corpus)
        print(json.dumps(gate, indent=2))
        return 0
    if "--run" in argv:
        try:
            results = run_eval(root, out_dir=os.path.join(root, "docs", "quality"))
        except RuntimeError as ex:
            print(f"REFUSED: {ex}")
            return 4
        print(render_markdown(results))
        print(f"[retrieval-eval] run_status={results['run_status']} -> "
              f"docs/quality/{RESULTS_BASENAME.format(date=results['date'])}")
        return 0
    print("usage: python -m cisco_toolkit.retrieval_eval --check | --gate | --run")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
