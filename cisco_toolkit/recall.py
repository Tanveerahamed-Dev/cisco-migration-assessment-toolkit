"""RRF hybrid recall (Phase 5, D10) — fuse ≥ 2 no-egress retrieval signals for ``/ask``.

Decision **D10**: multi-signal hybrid retrieval is "largely unexplored" — so this **ships as an experiment
with its own eval, not as proven SOTA**. The load-bearing, dependency-free core is **Reciprocal Rank
Fusion** (:func:`rrf_fuse`): given N ranked lists, an item's fused score is ``Σ 1/(k + rank)`` over the lists
it appears in — so an item ranked well by *several* signals beats one ranked well by only one, with no score
normalization needed.

An independent benchmark (arXiv `2601.07978` v4, Wolff & Bennati; re-verified 2026-07-23 against the primary
source — the Cognee row appears only from v3, not the Jan-2026 v1/v2; see ``memory/cognee-evaluation-2026-07-19.md``)
corroborates staying here rather than adopting an LLM-written ("cognify"-style) graph memory: on LoCoMo, that
architecture family scored 55.27-56.03% — Cognee and Graphiti statistically tied (p=0.845) — well below the
77-81% mem0/RAG/full-context cluster (p=0.002) this lexical+local-semantic hybrid sits architecturally closer to.

The no-egress signals fused here are two **local** corpora: the **docs** (prose) and the **code** (the
``cisco_toolkit`` sources — a lexical proxy for the graphify structural signal). Both are offline. Two more
stores plug into the same fusion when available: **graphify** (the AST graph, via :func:`graph_rank`, a
best-effort subprocess — offline) and the **vault digest** (D3/D4, ADR-0001 Amendment 1): a signed,
sanitized, provenance-**verified** corpus ranked **lexically** here (:func:`vault_digest_rank` — fence-clean,
always available when a digest exists), with an OPTIONAL local-Ollama semantic re-rank
(:func:`ollama_digest_rank`, gated — degrades to lexical). So a fused answer visibly draws on ≥ 2 stores —
the plan's recall metric.

Coverage-honest: a query with no lexical overlap returns nothing (not a fabricated hit); the eval reports the
measured lift (or *no* lift — "inconclusive"), never an assumed win. Pure-stdlib; :func:`rrf_fuse`,
:func:`lexical_rank`, and :func:`evaluate` do no I/O and are unit-tested without a repo.

P2-0a: the CLI's REAL query surfaces append each query to ``docs/quality/query_log.jsonl``
(:func:`log_query` — one JSON line of ``date``/``query``/``surface``, fail-open, local, no egress) so
D10's dense-lane precondition ("classify 30 real queries by type FIRST", d10 design §5) is runnable at
all; the synthetic ``--eval`` path never logs, so the recorded mix stays real.
"""
from __future__ import annotations

import datetime
import glob
import json
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

_WORD = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> List[str]:
    return _WORD.findall((text or "").lower())


def rrf_fuse(ranked_lists: List[List[Any]], *, k: int = 60) -> List[Tuple[Any, float]]:
    """Reciprocal Rank Fusion over ranked lists of item ids (best-first). Returns ``[(item, score)]``
    sorted by fused score desc (ties broken by item id for determinism). ``k`` (default 60) damps the
    contribution of low ranks."""
    scores: Dict[Any, float] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], str(kv[0])))


def lexical_rank(query: str, corpus: Dict[str, str], *, limit: int = 50) -> List[str]:
    """A dependency-free **TF-IDF** lexical signal over ``{doc_id: text}``. TF is length-normalized (term
    count / doc length); IDF is ``log((N+1)/(df+0.5))`` so *rare, discriminating* terms (``cooldown``,
    ``breaker``) dominate and ubiquitous ones (``the``, ``how``) contribute ~0 — no stopword list needed.
    Returns doc_ids best-first, only those with a non-zero score (no overlap -> excluded, never fabricated)."""
    qterms = set(tokenize(query))
    if not qterms:
        return []
    toks = {did: Counter(tokenize(text)) for did, text in corpus.items()}
    n = len(toks) or 1
    df = Counter()
    for c in toks.values():
        df.update(c.keys())
    idf = {t: math.log((n + 1) / (df[t] + 0.5)) for t in qterms}
    scored: List[Tuple[str, float]] = []
    for did, c in toks.items():
        total = sum(c.values()) or 1
        s = sum((c[t] / total) * idf[t] for t in qterms if c.get(t))
        if s > 0:
            scored.append((did, s))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return [did for did, _ in scored[:limit]]


def build_corpus(root: str, patterns: List[str]) -> Dict[str, str]:
    """Load ``{relpath: text}`` for every file matching the glob ``patterns`` under ``root``. Best-effort."""
    corpus: Dict[str, str] = {}
    for pat in patterns:
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    corpus[os.path.relpath(p, root)] = f.read()
            except OSError:
                pass
    return corpus


def graph_rank(query: str, *, timeout: int = 30) -> List[str]:
    """OPTIONAL third signal — graphify's scoped subgraph (offline AST). Best-effort: parses file/symbol
    identifiers from ``python -m graphify query``, first-seen order. Returns ``[]`` if graphify is
    unavailable (the hybrid simply degrades to the other signals — coverage-honest, never fabricated)."""
    try:
        import subprocess
        out = subprocess.run(["python", "-m", "graphify", "query", query],
                             capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return []
        seen: List[str] = []
        for m in re.finditer(r"[\w/\\.-]+\.(?:py|md)(?::\d+)?|\b[A-Za-z_][\w.]*\(\)", out.stdout or ""):
            tok = m.group(0)
            if tok not in seen:
                seen.append(tok)
        return seen[:50]
    except Exception:
        return []


# --- the vault-digest store (Phase 5, D3/D4, ADR-0001 Amendment 1) -----------------------------
# The one-way, sanitized, read-only vault digest. PRODUCED in the fenced lane (research_lane/vault_digest.py,
# outside cisco_toolkit/); the air-gapped repo only ever VERIFIES + reads the frozen signed digest here.
VAULT_DIGEST_DIR = os.path.join("docs", "vault-digest")


def load_vault_digest(digest_dir: str = VAULT_DIGEST_DIR, *, forbidden: Tuple[str, ...] = ()) -> Dict[str, str]:
    """Load + PROVENANCE-VERIFY the signed vault digest(s) into a ``{entry_id: text}`` corpus. Amendment 1
    point 2: the repo verifies before use — reuses :func:`cisco_toolkit.intel_feed.verify_feed` (sanitized +
    SHA-256 + forbidden-scan), the SAME gate as the intel feed. A refused digest is skipped whole (never
    partially consumed); no digest at all -> ``{}`` (coverage-honest — recall degrades to graph+docs, never a
    fabricated hit)."""
    from cisco_toolkit.intel_feed import verify_feed          # the shared sign/verify contract
    corpus: Dict[str, str] = {}
    for p in sorted(glob.glob(os.path.join(digest_dir, "digest-*.jsonl"))):
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        res = verify_feed(text, forbidden=forbidden)
        if not res["ok"]:
            continue
        for e in res["entries"]:
            corpus[str(e.get("id"))] = " ".join(str(e.get(f, "")) for f in ("title", "detail", "notes", "tags"))
    return corpus


def vault_digest_rank(query: str, digest_corpus: Dict[str, str], *, limit: int = 50) -> List[str]:
    """The vault-digest signal, LEXICAL (TF-IDF) — fence-clean, always available whenever a verified digest
    exists (needs no Ollama). The optional Ollama semantic re-rank is a separate, gated signal
    (:func:`ollama_digest_rank`)."""
    return lexical_rank(query, digest_corpus, limit=limit)


def ollama_digest_rank(query: str, *, digest_dir: str = VAULT_DIGEST_DIR, timeout: int = 10) -> List[str]:
    """OPTIONAL semantic signal via LOCAL Ollama (D4) — invoked as a SUBPROCESS (``ollama_recall.py`` lives
    OUTSIDE ``cisco_toolkit/`` so the no-egress import fence stays intact; the same pattern as
    :func:`graph_rank`). Returns ``[]`` when Ollama is absent/unreachable or the helper is missing — graceful
    degradation, so recall falls back to the lexical vault signal."""
    try:
        import subprocess
        helper = os.path.join(_repo_root(), "ollama_recall.py")
        if not os.path.exists(helper):
            return []
        out = subprocess.run(["python", helper, query, digest_dir],
                             capture_output=True, text=True, timeout=timeout, cwd=_repo_root())
        if out.returncode != 0:
            return []
        seen: List[str] = []
        for ln in (out.stdout or "").splitlines():
            tok = ln.strip()
            if tok and tok not in seen:
                seen.append(tok)
        return seen[:50]
    except Exception:
        return []


# --- the real-query log (P2-0a) -----------------------------------------------------------------
# D10's dense-lane precondition classifies the REAL query mix ("classify 30 real queries by type
# FIRST" — docs/d10-retrieval-eval-design-2026-07-08.md §5), which needs a log to exist at all.
# Only the REAL surfaces append here (this CLI, and /ask via ``--log-only --surface=ask``); the
# synthetic ones (--eval, the labeled experiment, unit tests) never do, so the mix stays real.
# Append-only, local, no egress; GITIGNORED/owner-machine like the vault digest — a real query may
# name client tokens from another engagement (two-store rule), so the rows never enter the pushable
# repo. Per-command opt-out: CISCO_RECALL_NO_LOG=1. Registered in docs/ssot.md (Law 1); never hand-edit.
QUERY_LOG_PATH = os.path.join("docs", "quality", "query_log.jsonl")


def log_query(query: str, surface: str = "recall", *, path: Optional[str] = None) -> bool:
    """Append ONE real query as one JSON line — exactly ``date``/``query``/``surface``, nothing else.
    FAIL-OPEN by contract: retrieval must never break because logging did, so any write failure
    (unwritable path, read-only tree) degrades silently to ``False`` — the same typed-except
    convention as :func:`build_corpus` / :func:`graph_rank`. Honors the per-command opt-out
    ``CISCO_RECALL_NO_LOG=1`` (returns ``False``, records nothing)."""
    if os.environ.get("CISCO_RECALL_NO_LOG") == "1":
        return False
    try:
        p = path or os.path.join(_repo_root(), QUERY_LOG_PATH)
        line = json.dumps({"date": datetime.date.today().isoformat(),
                           "query": str(query), "surface": str(surface)}, ensure_ascii=False)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except (OSError, ValueError, TypeError):
        return False


def hybrid_recall(query: str, *, docs_corpus: Dict[str, str], code_corpus: Dict[str, str],
                  k: int = 60, extra_lists: Optional[List[List[Any]]] = None) -> List[Tuple[Any, float]]:
    """Fuse the docs + code lexical signals (plus any ``extra_lists``, e.g. ``graph_rank`` output or a
    future Ollama vault-digest ranking) via RRF. The fused result draws on ≥ 2 stores."""
    lists: List[List[Any]] = [lexical_rank(query, docs_corpus), lexical_rank(query, code_corpus)]
    lists += [e for e in (extra_lists or []) if e]
    return rrf_fuse([l for l in lists if l], k=k)


# The D10 experiment's labeled set — real (query -> expected source file) pairs over this repo.
_EVAL_LABELS: List[Tuple[str, str]] = [
    ("circuit breaker cooldown nightly spend ceiling", "clock.py"),
    ("scorecard trend renderer counterexamples sparkline", "scorecard.py"),
    ("PIR calibration gap N floor descriptive", "calibration.py"),
    ("domain pack selection architecture coverage", "domain_packs.py"),
    ("council refute-first majority lens", "council.py"),
    ("intel feed provenance sanitized signed", "intel_feed.py"),
    ("self healing drift remediation propose only", "self_healing.py"),
    ("agent system self check non vacuous guard", "selfcheck.py"),
]


def evaluate(labeled: List[Tuple[str, str]], *, docs_corpus: Dict[str, str],
             code_corpus: Dict[str, str], k: int = 60) -> Dict[str, Any]:
    """The experiment (D10): does fusing docs+code beat the **best single signal**? A docs-only baseline
    can't win when the labels are code files, so the fair question is hybrid vs ``max(docs-only,
    code-only)``. Compares MRR (mean reciprocal rank of the expected file) over ``labeled`` (query,
    expected_substring) pairs. Reports the measured lift honestly — ``delta <= 0`` is called *no lift /
    inconclusive*, never spun as a win (D10: an experiment, not proven SOTA)."""
    def _rr(ranked: List[Any], expected: str) -> float:
        for i, item in enumerate(ranked, 1):
            if expected in str(item):
                return 1.0 / i
        return 0.0

    rr_docs, rr_code, rr_hyb = [], [], []
    for q, exp in labeled:
        rr_docs.append(_rr(lexical_rank(q, docs_corpus), exp))
        rr_code.append(_rr(lexical_rank(q, code_corpus), exp))
        hyb = [item for item, _ in hybrid_recall(q, docs_corpus=docs_corpus, code_corpus=code_corpus, k=k)]
        rr_hyb.append(_rr(hyb, exp))
    n = len(labeled) or 1
    md, mc, mh = (round(sum(x) / n, 3) for x in (rr_docs, rr_code, rr_hyb))
    best_single = max(md, mc)
    delta = round(mh - best_single, 3)
    verdict = ("fusion lifts recall over the best single signal (positive)" if delta > 0 else
               ("fusion matches the best single signal — no lift, no harm" if delta == 0 else
                "fusion UNDERPERFORMS the best single signal — negative; do not adopt on this evidence"))
    return {"n": len(labeled), "mrr_docs": md, "mrr_code": mc, "mrr_hybrid": mh,
            "best_single": best_single, "delta": delta,
            "note": f"hybrid {mh} vs best single {best_single} (docs {md}, code {mc}) over {len(labeled)} "
                    f"queries — {verdict}"}


def _repo_root() -> str:
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python -m cisco_toolkit.recall "<query>"`` fuses docs+code (and graphify if present) for the
    query; ``--eval`` runs the D10 experiment over the labeled set (synthetic — never logged);
    ``--log-only`` (with optional ``--surface=NAME``) records the query in the P2-0a real-query log
    WITHOUT retrieving — the arm the prose-only ``/ask`` command invokes (``--surface=ask``).
    Read-only, no egress."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    root = _repo_root()
    if "--eval" in argv:                       # the labeled experiment — synthetic, NEVER logged (P2-0a)
        docs = build_corpus(root, ["docs/**/*.md", "*.md"])
        code = build_corpus(root, ["cisco_toolkit/*.py"])
        rep = evaluate(_EVAL_LABELS, docs_corpus=docs, code_corpus=code)
        print(f"RRF recall eval (D10 experiment) — {rep['note']}")
        print(f"  n={rep['n']}  docs={rep['mrr_docs']}  code={rep['mrr_code']}  "
              f"hybrid={rep['mrr_hybrid']}  delta_vs_best_single={rep['delta']:+}")
        return 0
    query = " ".join(a for a in argv if not a.startswith("-"))
    if not query:
        print('usage: python -m cisco_toolkit.recall "<query>"   |   --eval   |   '
              '--log-only [--surface=ask] "<question>"')
        return 2
    surface = next((a.split("=", 1)[1] for a in argv if a.startswith("--surface=")), "") or "recall"
    logged = log_query(query, surface=surface)  # P2-0a: real query -> the mix log (fail-open)
    if "--log-only" in argv:
        print(f"logged (surface={surface}) -> {QUERY_LOG_PATH}" if logged else
              "query log unavailable — nothing recorded (fail-open)")
        return 0
    docs = build_corpus(root, ["docs/**/*.md", "*.md"])
    code = build_corpus(root, ["cisco_toolkit/*.py"])
    extra: List[List[Any]] = []
    g = graph_rank(query)                                       # offline graphify signal if available
    if g:
        extra.append(g)
    vault = load_vault_digest()                                 # verified signed vault digest (empty if none/gated)
    used_ollama = False
    if vault:
        extra.append(vault_digest_rank(query, vault))
        o = ollama_digest_rank(query)                           # optional LOCAL-Ollama semantic re-rank (gated)
        if o:
            extra.append(o)
            used_ollama = True
    fused = hybrid_recall(query, docs_corpus=docs, code_corpus=code, extra_lists=extra or None)
    stores = ("docs+code" + ("+graphify" if g else "") + ("+vault" if vault else "")
              + ("+ollama" if used_ollama else ""))
    print(f'recall "{query}" (fused: {stores}):')
    for item, score in fused[:10]:
        print(f"  {score:.4f}  {item}")
    if not fused:
        print("  (no lexical overlap in any store — nothing to recall)")
    if not vault:
        print("  [vault-digest: none/gated — degraded to graph+docs+code (ADR-0001 Amendment 1)]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
